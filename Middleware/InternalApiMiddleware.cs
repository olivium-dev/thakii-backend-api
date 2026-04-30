namespace ThakiiBackend.Api.Middleware;

/// <summary>
/// Gate for the <c>/internal/*</c> routes that the worker calls.
///
/// Behavior is controlled by two settings (both env vars take precedence
/// over <c>appsettings.json</c>):
///
///   * <c>Internal:WorkerSecret</c> / <c>INTERNAL_WORKER_SECRET</c> — the
///     shared secret. If empty, the middleware is effectively disabled
///     (used during initial rollout before the worker has the secret).
///
///   * <c>Internal:RequireSecret</c> / <c>INTERNAL__REQUIRE_SECRET</c> —
///     when <c>true</c>, missing/wrong secrets are rejected with HTTP 401.
///     When <c>false</c> (default), bad calls are *logged* but allowed,
///     so we can observe the rollout without breaking older workers.
///
/// Two-phase rollout:
///   1. Deploy backend with <c>RequireSecret=false</c> + a real
///      <c>WorkerSecret</c>. Backend logs every unsigned hit.
///   2. Deploy worker with the same secret in <c>INTERNAL_WORKER_SECRET</c>.
///   3. Confirm logs show no more unsigned hits, then flip
///      <c>RequireSecret</c> to <c>true</c> and restart the backend.
/// </summary>
public class InternalApiMiddleware
{
    private const string HeaderName = "X-Internal-Secret";
    private readonly RequestDelegate _next;
    private readonly IConfiguration _config;
    private readonly ILogger<InternalApiMiddleware> _logger;

    public InternalApiMiddleware(
        RequestDelegate next,
        IConfiguration config,
        ILogger<InternalApiMiddleware> logger)
    {
        _next = next;
        _config = config;
        _logger = logger;
    }

    private string? ConfiguredSecret =>
        Environment.GetEnvironmentVariable("INTERNAL_WORKER_SECRET")
        ?? _config["Internal:WorkerSecret"];

    private bool RequireSecret =>
        (Environment.GetEnvironmentVariable("INTERNAL__REQUIRE_SECRET")
         ?? _config["Internal:RequireSecret"]
         ?? "false").Equals("true", StringComparison.OrdinalIgnoreCase);

    public async Task InvokeAsync(HttpContext context)
    {
        var path = context.Request.Path.Value ?? string.Empty;
        if (!path.StartsWith("/internal/", StringComparison.OrdinalIgnoreCase))
        {
            await _next(context);
            return;
        }

        var configured = ConfiguredSecret;
        if (string.IsNullOrEmpty(configured))
        {
            // No secret configured at all → middleware is dormant. This is
            // the intentional initial state during rollout; we don't even
            // log a warning to avoid log spam.
            await _next(context);
            return;
        }

        var provided = context.Request.Headers.TryGetValue(HeaderName, out var values)
            ? values.ToString()
            : null;
        var matches = !string.IsNullOrEmpty(provided)
                      && CryptographicEquals(provided, configured);

        if (matches)
        {
            await _next(context);
            return;
        }

        // Unauthenticated /internal/* call. Log enough to find the source.
        var ip = context.Connection.RemoteIpAddress?.ToString() ?? "unknown";
        var ua = context.Request.Headers.UserAgent.ToString();
        _logger.LogWarning(
            "Unsigned /internal call: path={Path}, ip={Ip}, user_agent={UserAgent}, require_secret={Require}",
            path, ip, ua, RequireSecret);

        if (RequireSecret)
        {
            context.Response.StatusCode = StatusCodes.Status401Unauthorized;
            await context.Response.WriteAsync("{\"error\":\"missing or invalid X-Internal-Secret\"}");
            return;
        }

        await _next(context);
    }

    /// <summary>
    /// Constant-time string compare to avoid leaking the secret via
    /// timing differences. Both inputs are treated as UTF-8 byte arrays.
    /// </summary>
    private static bool CryptographicEquals(string a, string b)
    {
        var aBytes = System.Text.Encoding.UTF8.GetBytes(a);
        var bBytes = System.Text.Encoding.UTF8.GetBytes(b);
        if (aBytes.Length != bBytes.Length) return false;
        return System.Security.Cryptography.CryptographicOperations.FixedTimeEquals(aBytes, bBytes);
    }
}

public static class InternalApiMiddlewareExtensions
{
    public static IApplicationBuilder UseInternalApiGate(this IApplicationBuilder app) =>
        app.UseMiddleware<InternalApiMiddleware>();
}
