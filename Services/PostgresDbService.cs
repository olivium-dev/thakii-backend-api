using Npgsql;
using System.Text.Json;
using ThakiiBackend.Api.Models;

namespace ThakiiBackend.Api.Services;

public interface IPostgresDbService
{
    Task<Dictionary<string, object?>?> CreateVideoTaskAsync(string videoId, string filename, string userId, string userEmail, string status = "in_queue", string? s3Key = null);
    Task<Dictionary<string, object?>?> GetVideoTaskAsync(string videoId);
    Task<bool> UpdateVideoTaskAsync(string videoId, Dictionary<string, object?> updates);
    Task<List<Dictionary<string, object?>>> GetAllVideoTasksAsync();
    Task<List<Dictionary<string, object?>>> GetUserVideoTasksAsync(string userId);
    Task<bool> DeleteVideoTaskAsync(string videoId);
    Task<bool> CancelVideoTaskAsync(string videoId, string cancelledBy, string reason);
    Task<Dictionary<string, int>> GetAdminStatsAsync();

    // Worker API methods
    Task<Dictionary<string, object?>?> PickupTaskAsync(string workerId, int workerCapacity = 4);
    Task<bool> UpdateWorkerTaskAsync(string videoId, string workerId, string status, int? progress = null, string? pdfUrl = null, string? errorMessage = null, Dictionary<string, int>? stageDurations = null);
    Task<List<Dictionary<string, object?>>> GetPendingTasksAsync(int limit = 10);
    Task<bool> IsTaskCancellationRequestedAsync(string videoId);
    Task<bool> CompleteCancellationAsync(string videoId);
    Task<int> RecoverStaleTasksAsync();
    void RecordWorkerHeartbeat(string workerId, List<string>? activeTaskIds);

    // Phase B3: persist heartbeat to PostgreSQL so the reaper has a real
    // signal to act on instead of an in-memory dictionary.
    Task<int> PersistWorkerHeartbeatAsync(string workerId, List<string>? activeTaskIds);

    // Phase B4: reaper sweep + per-task requeue. Returns the list of
    // (videoId, attempts, action) so the caller can log / refund.
    Task<List<(string VideoId, int Attempts, string Action)>> RequeueStaleProcessingAsync(
        TimeSpan heartbeatStale,
        TimeSpan noHeartbeatGrace,
        int maxAttempts,
        TimeSpan? noForwardProgress = null,
        TimeSpan? hardCeiling = null);

    // Phase B7: admin requeue of an arbitrary video.
    Task<bool> RequeueVideoAsync(string videoId, string actor);

    // Phase 3: fine-grained progress from the worker subprocess.
    Task<bool> RecordTaskProgressAsync(string videoId, string phase, string? detailJson);

    // Phase 7: read-only peek at the next task candidate (no row update).
    Task<Dictionary<string, object?>?> PeekNextTaskAsync();

    // Phase B9: metrics buckets used by /admin/metrics/stuck-tasks.
    Task<Dictionary<string, int>> GetStuckTaskMetricsAsync();
}

public class PostgresDbService : IPostgresDbService
{
    private readonly string _connectionString;
    private readonly ILogger<PostgresDbService> _logger;

    // In-memory worker heartbeat tracking (like Python's worker_task_manager)
    private readonly System.Collections.Concurrent.ConcurrentDictionary<string, (DateTime LastHeartbeat, List<string> ActiveTasks)> _workerHeartbeats = new();

    public PostgresDbService(IConfiguration config, ILogger<PostgresDbService> logger)
    {
        var host = Environment.GetEnvironmentVariable("POSTGRES_HOST") ?? config["Postgres:Host"] ?? "localhost";
        var port = Environment.GetEnvironmentVariable("POSTGRES_PORT") ?? config["Postgres:Port"] ?? "5432";
        var db = Environment.GetEnvironmentVariable("POSTGRES_DB") ?? config["Postgres:Database"] ?? "thakii_production";
        var user = Environment.GetEnvironmentVariable("POSTGRES_USER") ?? config["Postgres:User"] ?? "postgres";
        var pass = Environment.GetEnvironmentVariable("POSTGRES_PASSWORD") ?? config["Postgres:Password"] ?? "";
        _connectionString = $"Host={host};Port={port};Database={db};Username={user};Password={pass}";
        _logger = logger;
    }

    private static Dictionary<string, object?> ToDict(NpgsqlDataReader reader)
    {
        var dict = new Dictionary<string, object?>();
        for (var i = 0; i < reader.FieldCount; i++)
        {
            var name = reader.GetName(i);
            var value = reader.GetValue(i);
            if (value is DateTime dt)
                dict[name] = dt.ToString("o");
            else
                dict[name] = value;
        }
        return dict;
    }

    public async Task<Dictionary<string, object?>?> CreateVideoTaskAsync(string videoId, string filename, string userId, string userEmail, string status = "in_queue", string? s3Key = null)
    {
        await using var conn = new NpgsqlConnection(_connectionString);
        await conn.OpenAsync();
        await using var cmd = new NpgsqlCommand(@"
            INSERT INTO video_tasks (video_id, filename, user_id, user_email, status, upload_date, s3_key)
            VALUES (@videoId, @filename, @userId, @userEmail, @status, @now, @s3Key)
            RETURNING *
        ", conn);
        cmd.Parameters.AddWithValue("videoId", videoId);
        cmd.Parameters.AddWithValue("filename", filename);
        cmd.Parameters.AddWithValue("userId", userId);
        cmd.Parameters.AddWithValue("userEmail", userEmail);
        cmd.Parameters.AddWithValue("status", status);
        cmd.Parameters.AddWithValue("now", DateTime.UtcNow);
        cmd.Parameters.AddWithValue("s3Key", (object?)s3Key ?? DBNull.Value);
        await using var reader = await cmd.ExecuteReaderAsync();
        if (await reader.ReadAsync())
            return ToDict(reader);
        return null;
    }

    public async Task<Dictionary<string, object?>?> GetVideoTaskAsync(string videoId)
    {
        await using var conn = new NpgsqlConnection(_connectionString);
        await conn.OpenAsync();
        await using var cmd = new NpgsqlCommand("SELECT * FROM video_tasks WHERE video_id = @videoId", conn);
        cmd.Parameters.AddWithValue("videoId", videoId);
        await using var reader = await cmd.ExecuteReaderAsync();
        if (await reader.ReadAsync())
            return ToDict(reader);
        return null;
    }

    public async Task<bool> UpdateVideoTaskAsync(string videoId, Dictionary<string, object?> updates)
    {
        if (updates.Count == 0) return false;
        var setClauses = updates.Keys.Select(k => $"{k} = @{k}").ToArray();
        var sql = $"UPDATE video_tasks SET {string.Join(", ", setClauses)} WHERE video_id = @videoId";
        await using var conn = new NpgsqlConnection(_connectionString);
        await conn.OpenAsync();
        await using var cmd = new NpgsqlCommand(sql, conn);
        foreach (var kv in updates)
            cmd.Parameters.AddWithValue(kv.Key, kv.Value ?? DBNull.Value);
        cmd.Parameters.AddWithValue("videoId", videoId);
        var rows = await cmd.ExecuteNonQueryAsync();
        return rows > 0;
    }

    public async Task<List<Dictionary<string, object?>>> GetAllVideoTasksAsync()
    {
        var list = new List<Dictionary<string, object?>>();
        await using var conn = new NpgsqlConnection(_connectionString);
        await conn.OpenAsync();
        await using var cmd = new NpgsqlCommand("SELECT * FROM video_tasks WHERE (cancelled IS NULL OR cancelled = FALSE) ORDER BY created_at DESC", conn);
        await using var reader = await cmd.ExecuteReaderAsync();
        while (await reader.ReadAsync())
            list.Add(ToDict(reader));
        return list;
    }

    public async Task<List<Dictionary<string, object?>>> GetUserVideoTasksAsync(string userId)
    {
        var list = new List<Dictionary<string, object?>>();
        await using var conn = new NpgsqlConnection(_connectionString);
        await conn.OpenAsync();
        await using var cmd = new NpgsqlCommand("SELECT * FROM video_tasks WHERE user_id = @userId AND (cancelled IS NULL OR cancelled = FALSE) ORDER BY created_at DESC", conn);
        cmd.Parameters.AddWithValue("userId", userId);
        await using var reader = await cmd.ExecuteReaderAsync();
        while (await reader.ReadAsync())
            list.Add(ToDict(reader));
        return list;
    }

    public async Task<bool> DeleteVideoTaskAsync(string videoId)
    {
        await using var conn = new NpgsqlConnection(_connectionString);
        await conn.OpenAsync();
        await using var cmd = new NpgsqlCommand("DELETE FROM video_tasks WHERE video_id = @videoId", conn);
        cmd.Parameters.AddWithValue("videoId", videoId);
        return await cmd.ExecuteNonQueryAsync() > 0;
    }

    public async Task<bool> CancelVideoTaskAsync(string videoId, string cancelledBy, string reason)
    {
        await using var conn = new NpgsqlConnection(_connectionString);
        await conn.OpenAsync();
        await using var cmd = new NpgsqlCommand("SELECT cancel_video_task(@p1, @p2, @p3)", conn);
        cmd.Parameters.AddWithValue("p1", videoId);
        cmd.Parameters.AddWithValue("p2", cancelledBy);
        cmd.Parameters.AddWithValue("p3", reason);
        var result = await cmd.ExecuteScalarAsync();
        return result is bool b && b;
    }

    public async Task<Dictionary<string, int>> GetAdminStatsAsync()
    {
        var stats = new Dictionary<string, int> { ["totalUsers"] = 0, ["totalVideos"] = 0, ["totalPDFs"] = 0, ["activeProcessing"] = 0 };
        await using var conn = new NpgsqlConnection(_connectionString);
        await conn.OpenAsync();
        await using (var cmd = new NpgsqlCommand("SELECT COUNT(DISTINCT user_id) FROM video_tasks", conn))
            stats["totalUsers"] = Convert.ToInt32(await cmd.ExecuteScalarAsync() ?? 0);
        await using (var cmd = new NpgsqlCommand("SELECT COUNT(*) FROM video_tasks", conn))
            stats["totalVideos"] = Convert.ToInt32(await cmd.ExecuteScalarAsync() ?? 0);
        await using (var cmd = new NpgsqlCommand("SELECT COUNT(*) FROM video_tasks WHERE status IN ('done', 'completed')", conn))
            stats["totalPDFs"] = Convert.ToInt32(await cmd.ExecuteScalarAsync() ?? 0);
        await using (var cmd = new NpgsqlCommand("SELECT COUNT(*) FROM video_tasks WHERE status IN ('in_progress', 'processing')", conn))
            stats["activeProcessing"] = Convert.ToInt32(await cmd.ExecuteScalarAsync() ?? 0);
        return stats;
    }

    // ========== Worker API Methods ==========

    /// <summary>
    /// Phase 2: compute an adaptive timeout for a task based on its stored
    /// video_duration_seconds.  Formula: clamp(duration * 0.6 + 600) * 1.5,
    /// within [900, 14400] seconds.  Returns null when duration is unknown
    /// so the worker falls back to its env-level default.
    /// </summary>
    public static int? ComputeTaskTimeoutSeconds(int? durationSeconds)
    {
        if (durationSeconds is null or <= 0)
            return null;

        var expected = durationSeconds.Value * 0.6 + 600;
        var withSafety = expected * 1.5;
        return (int)Math.Clamp(withSafety, 900, 14400);
    }

    public async Task<Dictionary<string, object?>?> PickupTaskAsync(string workerId, int workerCapacity = 4)
    {
        await using var conn = new NpgsqlConnection(_connectionString);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand(@"
            UPDATE video_tasks
            SET status = 'processing',
                processing_start = CURRENT_TIMESTAMP,
                processing_started_at = CURRENT_TIMESTAMP,
                assigned_worker_id = @workerId,
                assigned_worker = @workerId,
                last_heartbeat = CURRENT_TIMESTAMP,
                assignment_time = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE video_id = (
                SELECT video_id FROM video_tasks
                WHERE status IN ('in_queue', 'uploaded')
                AND (cancelled = FALSE OR cancelled IS NULL)
                ORDER BY created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            RETURNING *
        ", conn);
        cmd.Parameters.AddWithValue("workerId", workerId);

        await using var reader = await cmd.ExecuteReaderAsync();
        if (await reader.ReadAsync())
        {
            var task = ToDict(reader);
            _logger.LogInformation("Worker {WorkerId} picked up task {VideoId}", workerId, task.GetValueOrDefault("video_id"));

            // Phase 2: attach adaptive timeout hint for the worker
            int? durationSec = null;
            if (task.TryGetValue("video_duration_seconds", out var raw) && raw is int d)
                durationSec = d;
            var hint = ComputeTaskTimeoutSeconds(durationSec);
            if (hint.HasValue)
                task["timeout_seconds_hint"] = hint.Value;

            return task;
        }
        return null;
    }

    public async Task<bool> UpdateWorkerTaskAsync(string videoId, string workerId, string status,
        int? progress = null, string? pdfUrl = null, string? errorMessage = null,
        Dictionary<string, int>? stageDurations = null)
    {
        await using var conn = new NpgsqlConnection(_connectionString);
        await conn.OpenAsync();

        // Every worker-driven update keeps the row "alive" for the reaper.
        var updates = new List<string>
        {
            "status = @status",
            "updated_at = CURRENT_TIMESTAMP",
            "last_heartbeat = CURRENT_TIMESTAMP",
            "assigned_worker_id = @workerId",
            "assigned_worker = @workerId"
        };
        var cmd = new NpgsqlCommand();

        if (progress.HasValue)
            updates.Add("progress_percent = @progress");
        if (pdfUrl != null)
            updates.Add("pdf_url = @pdfUrl");
        if (errorMessage != null)
            updates.Add("error_message = @errorMessage");
        if (status is "done" or "completed" or "failed")
            updates.Add("processing_end = CURRENT_TIMESTAMP");
        // A successful completion clears the retry counter so future stuck
        // detections start fresh if the same video is re-uploaded.
        if (status is "done" or "completed")
            updates.Add("attempts = 0");
        if (status is "failed" && errorMessage != null)
            updates.Add("last_failure_reason = @errorMessage");

        // Phase 8: persist per-stage timing columns
        if (stageDurations != null)
        {
            foreach (var (key, val) in stageDurations)
            {
                var col = key switch
                {
                    "download" => "download_seconds",
                    "audio" => "audio_seconds",
                    "frames" => "frames_seconds",
                    "transcribe" => "transcribe_seconds",
                    "pdf" => "pdf_seconds",
                    "upload" => "upload_seconds",
                    _ => null,
                };
                if (col != null)
                {
                    var paramName = $"@sd_{key}";
                    updates.Add($"{col} = {paramName}");
                    cmd.Parameters.AddWithValue(paramName.TrimStart('@'), val);
                }
            }
        }

        cmd.CommandText = $"UPDATE video_tasks SET {string.Join(", ", updates)} WHERE video_id = @videoId";
        cmd.Connection = conn;
        cmd.Parameters.AddWithValue("status", status);
        cmd.Parameters.AddWithValue("videoId", videoId);
        cmd.Parameters.AddWithValue("workerId", workerId);
        if (progress.HasValue)
            cmd.Parameters.AddWithValue("progress", progress.Value);
        if (pdfUrl != null)
            cmd.Parameters.AddWithValue("pdfUrl", pdfUrl);
        if (errorMessage != null)
            cmd.Parameters.AddWithValue("errorMessage", errorMessage);

        var rows = await cmd.ExecuteNonQueryAsync();
        return rows > 0;
    }

    public async Task<List<Dictionary<string, object?>>> GetPendingTasksAsync(int limit = 10)
    {
        var list = new List<Dictionary<string, object?>>();
        await using var conn = new NpgsqlConnection(_connectionString);
        await conn.OpenAsync();
        await using var cmd = new NpgsqlCommand(@"
            SELECT * FROM video_tasks
            WHERE status IN ('in_queue', 'uploaded')
            ORDER BY created_at ASC
            LIMIT @limit
        ", conn);
        cmd.Parameters.AddWithValue("limit", limit);
        await using var reader = await cmd.ExecuteReaderAsync();
        while (await reader.ReadAsync())
            list.Add(ToDict(reader));
        return list;
    }

    public async Task<bool> IsTaskCancellationRequestedAsync(string videoId)
    {
        await using var conn = new NpgsqlConnection(_connectionString);
        await conn.OpenAsync();
        await using var cmd = new NpgsqlCommand(@"
            SELECT cancellation_requested FROM video_tasks WHERE video_id = @videoId
        ", conn);
        cmd.Parameters.AddWithValue("videoId", videoId);
        var result = await cmd.ExecuteScalarAsync();
        return result is bool b && b;
    }

    public async Task<bool> CompleteCancellationAsync(string videoId)
    {
        await using var conn = new NpgsqlConnection(_connectionString);
        await conn.OpenAsync();
        await using var cmd = new NpgsqlCommand(@"
            UPDATE video_tasks
            SET status = 'cancelled', cancelled = TRUE, cancelled_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE video_id = @videoId
        ", conn);
        cmd.Parameters.AddWithValue("videoId", videoId);
        var rows = await cmd.ExecuteNonQueryAsync();
        return rows > 0;
    }

    public async Task<int> RecoverStaleTasksAsync()
    {
        await using var conn = new NpgsqlConnection(_connectionString);
        await conn.OpenAsync();
        // Recover tasks stuck in 'processing' for more than 30 minutes
        await using var cmd = new NpgsqlCommand(@"
            UPDATE video_tasks
            SET status = 'in_queue', updated_at = CURRENT_TIMESTAMP, processing_start = NULL
            WHERE status = 'processing'
            AND processing_start < CURRENT_TIMESTAMP - INTERVAL '30 minutes'
        ", conn);
        return await cmd.ExecuteNonQueryAsync();
    }

    public void RecordWorkerHeartbeat(string workerId, List<string>? activeTaskIds)
    {
        _workerHeartbeats[workerId] = (DateTime.UtcNow, activeTaskIds ?? new List<string>());
    }

    public async Task<int> PersistWorkerHeartbeatAsync(string workerId, List<string>? activeTaskIds)
    {
        // Refresh last_heartbeat for every task currently attributed to this worker.
        // If activeTaskIds is non-empty, scope the update to that subset so the
        // worker can drop tasks from its hot set (e.g. after a crash recovery).
        await using var conn = new NpgsqlConnection(_connectionString);
        await conn.OpenAsync();

        var hasActive = activeTaskIds is { Count: > 0 };
        var sql = hasActive
            ? @"UPDATE video_tasks
                SET last_heartbeat = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE assigned_worker_id = @workerId
                  AND status = 'processing'
                  AND video_id = ANY(@activeIds)"
            : @"UPDATE video_tasks
                SET last_heartbeat = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE assigned_worker_id = @workerId
                  AND status = 'processing'";

        await using var cmd = new NpgsqlCommand(sql, conn);
        cmd.Parameters.AddWithValue("workerId", workerId);
        if (hasActive)
            cmd.Parameters.AddWithValue("activeIds", activeTaskIds!.ToArray());

        return await cmd.ExecuteNonQueryAsync();
    }

    public async Task<List<(string VideoId, int Attempts, string Action)>> RequeueStaleProcessingAsync(
        TimeSpan heartbeatStale,
        TimeSpan noHeartbeatGrace,
        int maxAttempts,
        TimeSpan? noForwardProgress = null,
        TimeSpan? hardCeiling = null)
    {
        var results = new List<(string, int, string)>();
        var useForwardProgress = noForwardProgress.HasValue;
        var effectiveNoFwdProgress = noForwardProgress ?? TimeSpan.FromMinutes(15);
        var effectiveHardCeiling = hardCeiling ?? TimeSpan.FromHours(4);

        await using var conn = new NpgsqlConnection(_connectionString);
        await conn.OpenAsync();
        await using var tx = await conn.BeginTransactionAsync();

        // Phase 4: smarter predicate. A row is reaped when:
        //   (heartbeat stale AND no forward progress) OR hard ceiling exceeded
        // When UseForwardProgress is off, falls back to heartbeat-only logic.
        await using var selectCmd = new NpgsqlCommand(@"
            SELECT video_id, attempts, last_heartbeat, processing_start, updated_at, last_forward_progress_at
            FROM video_tasks
            WHERE status = 'processing'
              AND (
                   (
                     (last_heartbeat IS NOT NULL AND last_heartbeat < NOW() - @heartbeatStale)
                     AND (@useForwardProgress = FALSE
                          OR last_forward_progress_at IS NULL
                          OR last_forward_progress_at < NOW() - @noForwardProgress)
                     AND (processing_start IS NULL OR processing_start < NOW() - @noHeartbeatGrace)
                   )
                OR (last_heartbeat IS NULL AND processing_start IS NOT NULL
                     AND processing_start < NOW() - @noHeartbeatGrace)
                OR (last_heartbeat IS NULL AND processing_start IS NULL
                     AND updated_at < NOW() - @noHeartbeatGrace)
                OR (processing_start IS NOT NULL
                     AND processing_start < NOW() - @hardCeiling)
              )
            FOR UPDATE SKIP LOCKED
        ", conn, tx);
        selectCmd.Parameters.AddWithValue("heartbeatStale", heartbeatStale);
        selectCmd.Parameters.AddWithValue("noHeartbeatGrace", noHeartbeatGrace);
        selectCmd.Parameters.AddWithValue("useForwardProgress", useForwardProgress);
        selectCmd.Parameters.AddWithValue("noForwardProgress", effectiveNoFwdProgress);
        selectCmd.Parameters.AddWithValue("hardCeiling", effectiveHardCeiling);

        var stale = new List<(string VideoId, int Attempts)>();
        await using (var reader = await selectCmd.ExecuteReaderAsync())
        {
            while (await reader.ReadAsync())
            {
                var videoId = reader.GetString(0);
                var attempts = reader.IsDBNull(1) ? 0 : reader.GetInt32(1);
                stale.Add((videoId, attempts));
            }
        }

        foreach (var (videoId, attempts) in stale)
        {
            var nextAttempts = attempts + 1;
            string action;

            if (nextAttempts > maxAttempts)
            {
                action = "failed";
                await using var failCmd = new NpgsqlCommand(@"
                    UPDATE video_tasks
                    SET status = 'failed',
                        error_message = COALESCE(error_message, 'auto-requeue gave up after ' || @max || ' attempts'),
                        last_failure_reason = 'auto-requeue gave up after ' || @max || ' attempts',
                        attempts = @attempts,
                        processing_end = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE video_id = @videoId
                ", conn, tx);
                failCmd.Parameters.AddWithValue("videoId", videoId);
                failCmd.Parameters.AddWithValue("attempts", nextAttempts);
                failCmd.Parameters.AddWithValue("max", maxAttempts);
                await failCmd.ExecuteNonQueryAsync();
            }
            else
            {
                action = "requeued";
                await using var requeueCmd = new NpgsqlCommand(@"
                    UPDATE video_tasks
                    SET status = 'in_queue',
                        progress_percent = 0,
                        processing_start = NULL,
                        processing_started_at = NULL,
                        processing_end = NULL,
                        assigned_worker_id = NULL,
                        assigned_worker = NULL,
                        last_heartbeat = NULL,
                        assignment_time = NULL,
                        processed_by_worker = NULL,
                        progress_phase = NULL,
                        progress_detail = NULL,
                        last_forward_progress_at = NULL,
                        attempts = @attempts,
                        last_failure_reason = COALESCE(last_failure_reason, 'auto-requeued: stale processing'),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE video_id = @videoId
                ", conn, tx);
                requeueCmd.Parameters.AddWithValue("videoId", videoId);
                requeueCmd.Parameters.AddWithValue("attempts", nextAttempts);
                await requeueCmd.ExecuteNonQueryAsync();
            }

            results.Add((videoId, nextAttempts, action));
        }

        await tx.CommitAsync();
        return results;
    }

    public async Task<bool> RequeueVideoAsync(string videoId, string actor)
    {
        await using var conn = new NpgsqlConnection(_connectionString);
        await conn.OpenAsync();
        await using var cmd = new NpgsqlCommand(@"
            UPDATE video_tasks
            SET status = 'in_queue',
                progress_percent = 0,
                error_message = NULL,
                processing_start = NULL,
                processing_started_at = NULL,
                processing_end = NULL,
                assigned_worker_id = NULL,
                assigned_worker = NULL,
                last_heartbeat = NULL,
                assignment_time = NULL,
                processed_by_worker = NULL,
                attempts = COALESCE(attempts, 0) + 1,
                last_failure_reason = 'manual requeue by ' || @actor,
                updated_at = CURRENT_TIMESTAMP
            WHERE video_id = @videoId
        ", conn);
        cmd.Parameters.AddWithValue("videoId", videoId);
        cmd.Parameters.AddWithValue("actor", actor);
        var rows = await cmd.ExecuteNonQueryAsync();
        return rows > 0;
    }

    public async Task<Dictionary<string, int>> GetStuckTaskMetricsAsync()
    {
        var metrics = new Dictionary<string, int>
        {
            ["processing_no_heartbeat_5m"] = 0,
            ["processing_no_progress_15m"] = 0,
            ["in_queue_older_30m"] = 0,
            ["processing_total"] = 0,
            ["in_queue_total"] = 0
        };

        await using var conn = new NpgsqlConnection(_connectionString);
        await conn.OpenAsync();
        await using var cmd = new NpgsqlCommand(@"
            SELECT
              COUNT(*) FILTER (WHERE status='processing'
                               AND last_heartbeat IS NOT NULL
                               AND last_heartbeat < NOW() - INTERVAL '5 minutes')        AS processing_no_heartbeat_5m,
              COUNT(*) FILTER (WHERE status='processing'
                               AND last_heartbeat IS NULL
                               AND COALESCE(processing_start, updated_at) < NOW() - INTERVAL '15 minutes') AS processing_no_progress_15m,
              COUNT(*) FILTER (WHERE status IN ('in_queue','uploaded')
                               AND created_at < NOW() - INTERVAL '30 minutes')           AS in_queue_older_30m,
              COUNT(*) FILTER (WHERE status='processing')                                AS processing_total,
              COUNT(*) FILTER (WHERE status IN ('in_queue','uploaded'))                  AS in_queue_total
            FROM video_tasks
        ", conn);
        await using var reader = await cmd.ExecuteReaderAsync();
        if (await reader.ReadAsync())
        {
            metrics["processing_no_heartbeat_5m"] = Convert.ToInt32(reader.GetValue(0));
            metrics["processing_no_progress_15m"] = Convert.ToInt32(reader.GetValue(1));
            metrics["in_queue_older_30m"]        = Convert.ToInt32(reader.GetValue(2));
            metrics["processing_total"]          = Convert.ToInt32(reader.GetValue(3));
            metrics["in_queue_total"]            = Convert.ToInt32(reader.GetValue(4));
        }
        return metrics;
    }

    /// <summary>
    /// Phase 7: read-only peek at the next pickup candidate.  No row update,
    /// no FOR UPDATE lock.  Used by the worker prefetch thread to download
    /// the next video while transcribing the current one.
    /// </summary>
    public async Task<Dictionary<string, object?>?> PeekNextTaskAsync()
    {
        await using var conn = new NpgsqlConnection(_connectionString);
        await conn.OpenAsync();
        await using var cmd = new NpgsqlCommand(@"
            SELECT * FROM video_tasks
            WHERE status IN ('in_queue', 'uploaded')
              AND (cancelled = FALSE OR cancelled IS NULL)
            ORDER BY created_at ASC
            LIMIT 1
        ", conn);

        await using var reader = await cmd.ExecuteReaderAsync();
        if (await reader.ReadAsync())
            return ToDict(reader);
        return null;
    }

    /// <summary>
    /// Phase 3: record fine-grained progress from the worker without
    /// touching status. Sets last_forward_progress_at = NOW() server-side.
    /// Also synthesises progress_percent for backward-compat with frontend.
    /// </summary>
    public async Task<bool> RecordTaskProgressAsync(string videoId, string phase, string? detailJson)
    {
        await using var conn = new NpgsqlConnection(_connectionString);
        await conn.OpenAsync();

        // Synthesise a progress_percent from the phase + detail so the existing
        // frontend progress bar keeps moving smoothly.
        int? syntheticPercent = null;
        if (phase == "transcribe" && detailJson != null)
        {
            try
            {
                using var doc = System.Text.Json.JsonDocument.Parse(detailJson);
                var root = doc.RootElement;
                if (root.TryGetProperty("audio_seconds_done", out var doneProp) &&
                    root.TryGetProperty("audio_seconds_total", out var totalProp))
                {
                    var done = doneProp.GetDouble();
                    var total = totalProp.GetDouble();
                    if (total > 0)
                        syntheticPercent = 30 + (int)(50.0 * done / total);
                }
            }
            catch { /* best effort */ }
        }
        else if (phase == "download")
            syntheticPercent = 10;
        else if (phase == "audio")
            syntheticPercent = 25;
        else if (phase == "frames")
            syntheticPercent = 28;
        else if (phase == "pdf")
            syntheticPercent = 82;
        else if (phase == "upload")
            syntheticPercent = 90;

        var sql = @"
            UPDATE video_tasks
            SET progress_phase = @phase,
                progress_detail = @detail::jsonb,
                last_forward_progress_at = NOW()
                " + (syntheticPercent.HasValue ? ", progress_percent = @pct" : "") + @"
            WHERE video_id = @vid AND status = 'processing'";

        await using var cmd = new NpgsqlCommand(sql, conn);
        cmd.Parameters.AddWithValue("phase", phase);
        cmd.Parameters.AddWithValue("detail", (object?)detailJson ?? DBNull.Value);
        cmd.Parameters.AddWithValue("vid", videoId);
        if (syntheticPercent.HasValue)
            cmd.Parameters.AddWithValue("pct", syntheticPercent.Value);

        var rows = await cmd.ExecuteNonQueryAsync();
        return rows > 0;
    }
}
