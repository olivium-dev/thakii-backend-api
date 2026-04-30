using Microsoft.Extensions.Hosting;

namespace ThakiiBackend.Api.Services;

/// <summary>
/// Background loop that periodically reaps stale `processing` rows.
///
/// A row is "stale" when one of three things is true:
///   1. last_heartbeat is set but older than <c>HeartbeatStaleSeconds</c>.
///   2. last_heartbeat is NULL and processing_start is older than
///      <c>NoHeartbeatGraceSeconds</c> (worker died after pickup but before
///      its first heartbeat).
///   3. last_heartbeat is NULL and processing_start is NULL — worst case,
///      we fall back to <c>updated_at</c>.
///
/// On detection, the row is requeued (status='in_queue', worker columns
/// cleared, <c>attempts</c> incremented). After <c>MaxAttempts</c>
/// requeues, the row is marked <c>failed</c> and credits are refunded
/// through <see cref="IVideoCreditRefundService"/>.
///
/// Runtime kill switch: set <c>Reaper:Enabled=false</c> (or env
/// <c>REAPER__ENABLED=false</c>) to disable in place. Defaults to enabled.
/// </summary>
public class StaleTaskReaperService : BackgroundService
{
    private readonly IServiceProvider _services;
    private readonly IConfiguration _config;
    private readonly ILogger<StaleTaskReaperService> _logger;

    public StaleTaskReaperService(
        IServiceProvider services,
        IConfiguration config,
        ILogger<StaleTaskReaperService> logger)
    {
        _services = services;
        _config = config;
        _logger = logger;
    }

    private bool Enabled =>
        (Environment.GetEnvironmentVariable("REAPER__ENABLED")
         ?? _config["Reaper:Enabled"]
         ?? "true").Equals("true", StringComparison.OrdinalIgnoreCase);

    private TimeSpan SweepInterval =>
        TimeSpan.FromSeconds(int.TryParse(
            Environment.GetEnvironmentVariable("REAPER__SWEEP_SECONDS")
            ?? _config["Reaper:SweepSeconds"], out var v) ? Math.Max(v, 5) : 60);

    private TimeSpan HeartbeatStale =>
        TimeSpan.FromSeconds(int.TryParse(
            Environment.GetEnvironmentVariable("REAPER__HEARTBEAT_STALE_SECONDS")
            ?? _config["Reaper:HeartbeatStaleSeconds"], out var v) ? Math.Max(v, 60) : 300);

    private TimeSpan NoHeartbeatGrace =>
        TimeSpan.FromSeconds(int.TryParse(
            Environment.GetEnvironmentVariable("REAPER__NO_HEARTBEAT_GRACE_SECONDS")
            ?? _config["Reaper:NoHeartbeatGraceSeconds"], out var v) ? Math.Max(v, 60) : 900);

    private int MaxAttempts =>
        int.TryParse(
            Environment.GetEnvironmentVariable("REAPER__MAX_ATTEMPTS")
            ?? _config["Reaper:MaxAttempts"], out var v) ? Math.Max(v, 1) : 3;

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        _logger.LogInformation(
            "StaleTaskReaperService starting. enabled={Enabled}, sweep={Sweep}s, heartbeatStale={HbStale}s, noHbGrace={NoHbGrace}s, maxAttempts={MaxAttempts}",
            Enabled, SweepInterval.TotalSeconds, HeartbeatStale.TotalSeconds, NoHeartbeatGrace.TotalSeconds, MaxAttempts);

        // Tiny stagger so multiple replicas (if ever) don't hammer the DB at the same instant.
        try { await Task.Delay(TimeSpan.FromSeconds(Random.Shared.Next(5, 15)), stoppingToken); }
        catch (OperationCanceledException) { return; }

        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                if (!Enabled)
                {
                    _logger.LogDebug("StaleTaskReaperService disabled via config; skipping sweep");
                }
                else
                {
                    await SweepOnceAsync(stoppingToken);
                }
            }
            catch (OperationCanceledException)
            {
                break;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Reaper sweep failed; will retry after the regular interval");
            }

            try { await Task.Delay(SweepInterval, stoppingToken); }
            catch (OperationCanceledException) { break; }
        }

        _logger.LogInformation("StaleTaskReaperService stopping");
    }

    private async Task SweepOnceAsync(CancellationToken ct)
    {
        using var scope = _services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<IPostgresDbService>();
        var refundService = scope.ServiceProvider.GetService<IVideoCreditRefundService>();

        var results = await db.RequeueStaleProcessingAsync(HeartbeatStale, NoHeartbeatGrace, MaxAttempts);
        if (results.Count == 0)
        {
            _logger.LogDebug("Reaper sweep: no stale processing rows");
            return;
        }

        var requeued = 0;
        var failed = 0;
        foreach (var (videoId, attempts, action) in results)
        {
            if (action == "failed")
            {
                failed++;
                _logger.LogWarning(
                    "Reaper marked {VideoId} as FAILED after {Attempts} attempts (gave up)",
                    videoId, attempts);
                if (refundService != null)
                {
                    try
                    {
                        await refundService.RefundCreditsForVideoAsync(videoId,
                            $"auto-requeue gave up after {attempts} attempts");
                    }
                    catch (Exception ex)
                    {
                        _logger.LogError(ex, "Refund failed for reaped video {VideoId}", videoId);
                    }
                }
            }
            else
            {
                requeued++;
                _logger.LogWarning(
                    "Reaper requeued {VideoId} (attempt {Attempts}/{Max})",
                    videoId, attempts, MaxAttempts);
            }
        }

        _logger.LogInformation(
            "Reaper sweep complete: total={Total}, requeued={Requeued}, failed={Failed}",
            results.Count, requeued, failed);
    }
}
