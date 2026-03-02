using System.Text.Json;

namespace ThakiiBackend.Api.Middleware.SocketIo;

/// <summary>
/// ASP.NET Core middleware that serves the <c>/socket.io/</c> endpoint using
/// Engine.IO v4 HTTP long-polling, making the .NET backend wire-compatible
/// with <c>socket.io-client</c> v4.x (polling transport).
/// </summary>
public sealed class SocketIoMiddleware
{
    private const char RecordSeparator = '\x1e'; // EIO4 packet delimiter

    private readonly RequestDelegate _next;
    private readonly SocketIoServer _server;
    private readonly ILogger<SocketIoMiddleware> _logger;

    public SocketIoMiddleware(RequestDelegate next, SocketIoServer server, ILogger<SocketIoMiddleware> logger)
    {
        _next = next;
        _server = server;
        _logger = logger;
    }

    public async Task InvokeAsync(HttpContext ctx)
    {
        if (!ctx.Request.Path.StartsWithSegments("/socket.io"))
        {
            await _next(ctx);
            return;
        }

        var query = ctx.Request.Query;

        if (query["EIO"].FirstOrDefault() != "4")
        {
            ctx.Response.StatusCode = 400;
            await ctx.Response.WriteAsync("Unsupported EIO version");
            return;
        }

        if (query["transport"].FirstOrDefault() != "polling")
        {
            ctx.Response.StatusCode = 400;
            await ctx.Response.WriteAsync("Only polling transport is supported");
            return;
        }

        var sid = query["sid"].FirstOrDefault();

        switch (ctx.Request.Method)
        {
            case "GET" when string.IsNullOrEmpty(sid):
                await HandleHandshake(ctx);
                break;

            case "GET":
                await HandlePoll(ctx, sid!);
                break;

            case "POST" when !string.IsNullOrEmpty(sid):
                await HandlePost(ctx, sid!);
                break;

            default:
                ctx.Response.StatusCode = 400;
                break;
        }
    }

    // ──────────────────────────── Handshake (new session) ────────────────────────────

    private async Task HandleHandshake(HttpContext ctx)
    {
        var session = _server.CreateSession();

        var open = JsonSerializer.Serialize(new
        {
            sid = session.EngineSid,
            upgrades = Array.Empty<string>(),
            pingInterval = SocketIoServer.PingInterval,
            pingTimeout = SocketIoServer.PingTimeout,
            maxPayload = SocketIoServer.MaxPayload
        });

        ctx.Response.ContentType = "text/plain; charset=UTF-8";
        await ctx.Response.WriteAsync($"0{open}");
    }

    // ──────────────────────────── GET long-poll ────────────────────────────

    private async Task HandlePoll(HttpContext ctx, string sid)
    {
        var session = _server.GetSession(sid);
        if (session is null)
        {
            ctx.Response.StatusCode = 400;
            ctx.Response.ContentType = "application/json";
            await ctx.Response.WriteAsync("{\"code\":3,\"message\":\"Session ID unknown\"}");
            return;
        }

        session.LastActivity = DateTimeOffset.UtcNow;

        var packets = await session.DequeueAsync(TimeSpan.FromSeconds(20), ctx.RequestAborted);

        ctx.Response.ContentType = "text/plain; charset=UTF-8";

        if (packets.Count == 0)
        {
            await ctx.Response.WriteAsync("6"); // Engine.IO NOOP
        }
        else if (packets.Count == 1)
        {
            await ctx.Response.WriteAsync(packets[0]);
        }
        else
        {
            await ctx.Response.WriteAsync(string.Join(RecordSeparator, packets));
        }
    }

    // ──────────────────────────── POST (client → server packets) ────────────────────────────

    private async Task HandlePost(HttpContext ctx, string sid)
    {
        var session = _server.GetSession(sid);
        if (session is null)
        {
            ctx.Response.StatusCode = 400;
            ctx.Response.ContentType = "application/json";
            await ctx.Response.WriteAsync("{\"code\":3,\"message\":\"Session ID unknown\"}");
            return;
        }

        session.LastActivity = DateTimeOffset.UtcNow;

        using var reader = new StreamReader(ctx.Request.Body);
        var body = await reader.ReadToEndAsync();

        foreach (var raw in body.Split(RecordSeparator))
        {
            if (raw.Length > 0)
                ProcessClientPacket(session, raw);
        }

        ctx.Response.ContentType = "text/html; charset=utf-8";
        await ctx.Response.WriteAsync("ok");
    }

    // ──────────────────────────── Packet processing ────────────────────────────

    private void ProcessClientPacket(SocketIoSession session, string packet)
    {
        switch (packet[0])
        {
            case '3': // Engine.IO PONG
                session.LastActivity = DateTimeOffset.UtcNow;
                break;

            case '4' when packet.Length >= 2: // Engine.IO MESSAGE → unwrap to Socket.IO layer
                ProcessSocketIoPacket(session, packet.AsSpan(1));
                break;

            case '1': // Engine.IO CLOSE
                _server.DestroySession(session.EngineSid);
                break;
        }
    }

    private void ProcessSocketIoPacket(SocketIoSession session, ReadOnlySpan<char> packet)
    {
        if (packet.IsEmpty) return;

        switch (packet[0])
        {
            case '0': // Socket.IO CONNECT (default namespace)
                session.Connected = true;
                session.Enqueue($"40{{\"sid\":\"{session.SocketSid}\"}}");
                break;

            case '1': // Socket.IO DISCONNECT
                session.Connected = false;
                _server.DestroySession(session.EngineSid);
                break;

            case '2': // Socket.IO EVENT
                HandleEvent(session, packet.Slice(1));
                break;
        }
    }

    /// <summary>
    /// Parse and dispatch Socket.IO events. The <paramref name="json"/> payload starts after
    /// the Engine.IO + Socket.IO type prefixes and may optionally begin with an ack id.
    /// Expected shapes: <c>["join",{"user_id":"..."}]</c>, <c>["ping"]</c>.
    /// </summary>
    private void HandleEvent(SocketIoSession session, ReadOnlySpan<char> json)
    {
        // Skip optional acknowledgement id (digits before the '[')
        var bracketIdx = json.IndexOf('[');
        if (bracketIdx < 0) return;

        var arrayJson = json.Slice(bracketIdx).ToString();

        try
        {
            using var doc = JsonDocument.Parse(arrayJson);
            var arr = doc.RootElement;
            if (arr.ValueKind != JsonValueKind.Array || arr.GetArrayLength() < 1)
                return;

            var eventName = arr[0].GetString();

            switch (eventName)
            {
                case "join" when arr.GetArrayLength() >= 2:
                {
                    var userId = arr[1].TryGetProperty("user_id", out var v) ? v.GetString() : null;
                    if (string.IsNullOrEmpty(userId)) break;
                    var room = $"user_{userId}";
                    _server.JoinRoom(session.EngineSid, room);
                    var ack = JsonSerializer.Serialize(new { room, message = $"Joined room {room}" });
                    session.Enqueue($"42[\"joined\",{ack}]");
                    break;
                }

                case "leave" when arr.GetArrayLength() >= 2:
                {
                    var userId = arr[1].TryGetProperty("user_id", out var v) ? v.GetString() : null;
                    if (string.IsNullOrEmpty(userId)) break;
                    var room = $"user_{userId}";
                    _server.LeaveRoom(session.EngineSid, room);
                    var ack = JsonSerializer.Serialize(new { room, message = $"Left room {room}" });
                    session.Enqueue($"42[\"left\",{ack}]");
                    break;
                }

                case "ping":
                    session.Enqueue("42[\"pong\",{}]");
                    break;
            }
        }
        catch (JsonException ex)
        {
            _logger.LogWarning(ex, "Failed to parse Socket.IO event payload");
        }
    }
}
