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
    Task<bool> UpdateWorkerTaskAsync(string videoId, string workerId, string status, int? progress = null, string? pdfUrl = null, string? errorMessage = null);
    Task<List<Dictionary<string, object?>>> GetPendingTasksAsync(int limit = 10);
    Task<bool> IsTaskCancellationRequestedAsync(string videoId);
    Task<bool> CompleteCancellationAsync(string videoId);
    Task<int> RecoverStaleTasksAsync();
    void RecordWorkerHeartbeat(string workerId, List<string>? activeTaskIds);
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

    public async Task<Dictionary<string, object?>?> PickupTaskAsync(string workerId, int workerCapacity = 4)
    {
        await using var conn = new NpgsqlConnection(_connectionString);
        await conn.OpenAsync();

        // Atomically pick up a single task: set status to 'processing' and assign worker
        await using var cmd = new NpgsqlCommand(@"
            UPDATE video_tasks
            SET status = 'processing',
                processing_start = CURRENT_TIMESTAMP,
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

        await using var reader = await cmd.ExecuteReaderAsync();
        if (await reader.ReadAsync())
        {
            var task = ToDict(reader);
            _logger.LogInformation("Worker {WorkerId} picked up task {VideoId}", workerId, task.GetValueOrDefault("video_id"));
            return task;
        }
        return null;
    }

    public async Task<bool> UpdateWorkerTaskAsync(string videoId, string workerId, string status,
        int? progress = null, string? pdfUrl = null, string? errorMessage = null)
    {
        await using var conn = new NpgsqlConnection(_connectionString);
        await conn.OpenAsync();

        var updates = new List<string> { "status = @status", "updated_at = CURRENT_TIMESTAMP" };
        var cmd = new NpgsqlCommand();

        if (progress.HasValue)
            updates.Add("progress_percent = @progress");
        if (pdfUrl != null)
            updates.Add("pdf_url = @pdfUrl");
        if (errorMessage != null)
            updates.Add("error_message = @errorMessage");
        if (status is "done" or "completed" or "failed")
            updates.Add("processing_end = CURRENT_TIMESTAMP");

        cmd.CommandText = $"UPDATE video_tasks SET {string.Join(", ", updates)} WHERE video_id = @videoId";
        cmd.Connection = conn;
        cmd.Parameters.AddWithValue("status", status);
        cmd.Parameters.AddWithValue("videoId", videoId);
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
}
