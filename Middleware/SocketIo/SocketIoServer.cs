using System.Collections.Concurrent;
using System.Text.Json;
using System.Threading.Channels;

namespace ThakiiBackend.Api.Middleware.SocketIo;

/// <summary>
/// Lightweight Socket.IO server that implements just enough of the Engine.IO v4 / Socket.IO v4
/// polling protocol to be compatible with <c>socket.io-client</c> v4.x configured for polling transport.
/// </summary>
public sealed class SocketIoServer : IDisposable
{
    public const int PingInterval = 25000;
    public const int PingTimeout = 20000;
    public const int MaxPayload = 1_000_000;

    private readonly ConcurrentDictionary<string, SocketIoSession> _sessions = new();
    private readonly ConcurrentDictionary<string, ConcurrentDictionary<string, byte>> _rooms = new();
    private readonly Timer _maintenanceTimer;
    private readonly ILogger<SocketIoServer> _logger;

    public SocketIoServer(ILogger<SocketIoServer> logger)
    {
        _logger = logger;
        _maintenanceTimer = new Timer(Maintenance, null, PingInterval, PingInterval);
    }

    public SocketIoSession CreateSession()
    {
        var session = new SocketIoSession();
        _sessions[session.EngineSid] = session;
        _logger.LogDebug("Socket.IO session created: {Sid}", session.EngineSid);
        return session;
    }

    public SocketIoSession? GetSession(string sid) =>
        _sessions.TryGetValue(sid, out var s) ? s : null;

    public void DestroySession(string sid)
    {
        if (!_sessions.TryRemove(sid, out var session)) return;

        foreach (var room in _rooms.Values)
            room.TryRemove(sid, out _);

        session.Dispose();
        _logger.LogDebug("Socket.IO session destroyed: {Sid}", sid);
    }

    public void JoinRoom(string sid, string room)
    {
        _rooms.GetOrAdd(room, _ => new ConcurrentDictionary<string, byte>())[sid] = 0;
        _logger.LogDebug("Session {Sid} joined room {Room}", sid, room);
    }

    public void LeaveRoom(string sid, string room)
    {
        if (_rooms.TryGetValue(room, out var members))
            members.TryRemove(sid, out _);
    }

    /// <summary>
    /// Push a Socket.IO event to every session in <paramref name="room"/>.
    /// </summary>
    public void EmitToRoom(string room, string eventName, object data)
    {
        if (!_rooms.TryGetValue(room, out var members)) return;

        var json = JsonSerializer.Serialize(new object[] { eventName, data });
        var packet = $"42{json}";

        foreach (var sid in members.Keys)
        {
            if (_sessions.TryGetValue(sid, out var session))
                session.Enqueue(packet);
        }
    }

    private void Maintenance(object? state)
    {
        var cutoff = DateTimeOffset.UtcNow.AddMilliseconds(-(PingInterval + PingTimeout));

        foreach (var (sid, session) in _sessions)
        {
            if (session.LastActivity < cutoff)
            {
                _logger.LogDebug("Session {Sid} timed out", sid);
                DestroySession(sid);
                continue;
            }

            session.Enqueue("2"); // Engine.IO PING
        }
    }

    public void Dispose()
    {
        _maintenanceTimer.Dispose();
        foreach (var (_, session) in _sessions)
            session.Dispose();
    }
}

/// <summary>
/// Represents a single Engine.IO / Socket.IO polling session with an outbound message channel.
/// </summary>
public sealed class SocketIoSession : IDisposable
{
    public string EngineSid { get; } = GenerateId(20);
    public string SocketSid { get; } = GenerateId(8);
    public DateTimeOffset LastActivity { get; set; } = DateTimeOffset.UtcNow;
    public bool Connected { get; set; }

    private readonly Channel<string> _channel = Channel.CreateUnbounded<string>(
        new UnboundedChannelOptions { SingleReader = true });

    public void Enqueue(string packet) => _channel.Writer.TryWrite(packet);

    /// <summary>
    /// Wait for queued packets (long-poll). Returns as soon as at least one packet is available
    /// or <paramref name="timeout"/> elapses.
    /// </summary>
    public async Task<List<string>> DequeueAsync(TimeSpan timeout, CancellationToken ct)
    {
        var packets = new List<string>();

        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        cts.CancelAfter(timeout);

        try
        {
            if (await _channel.Reader.WaitToReadAsync(cts.Token))
            {
                while (_channel.Reader.TryRead(out var packet))
                    packets.Add(packet);
            }
        }
        catch (OperationCanceledException) { /* timeout or request aborted – return whatever we have */ }

        return packets;
    }

    public void Dispose() => _channel.Writer.TryComplete();

    private static string GenerateId(int length)
    {
        const string chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
        return string.Create(length, chars, static (span, c) =>
        {
            for (var i = 0; i < span.Length; i++)
                span[i] = c[Random.Shared.Next(c.Length)];
        });
    }
}
