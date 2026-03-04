using Npgsql;

namespace ThakiiBackend.Api.Services;

public interface IBatchImportService
{
    Task<Dictionary<string, object?>?> CreateBatchJobAsync(string userId, string userEmail, string shareUrl);
    Task<Dictionary<string, object?>?> GetBatchJobStatusAsync(string jobId, string userId);
    Task<List<Dictionary<string, object?>>> ListUserBatchJobsAsync(string userId, int limit = 20);
}

public class BatchImportService : IBatchImportService
{
    private readonly string _connectionString;
    private readonly IS3StorageService _s3;
    private readonly IPostgresDbService _db;
    private readonly IWorkerManagerService _workerManager;
    private readonly IConfiguration _config;
    private readonly ILogger<BatchImportService> _logger;
    private readonly IHttpClientFactory _httpClientFactory;

    private bool IsWorkerApiEnabled =>
        (Environment.GetEnvironmentVariable("ENABLE_WORKER_API") ?? _config["Worker:EnableWorkerApi"] ?? "false")
        .Equals("true", StringComparison.OrdinalIgnoreCase);

    public BatchImportService(IConfiguration config, IS3StorageService s3, IPostgresDbService db,
        IWorkerManagerService workerManager, ILogger<BatchImportService> logger, IHttpClientFactory httpClientFactory)
    {
        _s3 = s3;
        _db = db;
        _workerManager = workerManager;
        _config = config;
        _logger = logger;
        _httpClientFactory = httpClientFactory;

        var host = Environment.GetEnvironmentVariable("POSTGRES_HOST") ?? config["Postgres:Host"] ?? "localhost";
        var port = Environment.GetEnvironmentVariable("POSTGRES_PORT") ?? config["Postgres:Port"] ?? "5432";
        var database = Environment.GetEnvironmentVariable("POSTGRES_DB") ?? config["Postgres:Database"] ?? "thakii_production";
        var user = Environment.GetEnvironmentVariable("POSTGRES_USER") ?? config["Postgres:User"] ?? "postgres";
        var pass = Environment.GetEnvironmentVariable("POSTGRES_PASSWORD") ?? config["Postgres:Password"] ?? "";
        _connectionString = $"Host={host};Port={port};Database={database};Username={user};Password={pass}";
    }

    public async Task<Dictionary<string, object?>?> CreateBatchJobAsync(string userId, string userEmail, string shareUrl)
    {
        var jobId = Guid.NewGuid().ToString();

        try
        {
            // List videos from share URL (Nextcloud WebDAV)
            var videos = await ListVideosFromShareUrl(shareUrl);
            if (videos.Count == 0)
            {
                _logger.LogWarning("No videos found at share URL: {ShareUrl}", shareUrl);
                return null;
            }

            long totalSize = videos.Sum(v => v.Size);

            await using var conn = new NpgsqlConnection(_connectionString);
            await conn.OpenAsync();

            // Create batch job
            await using (var cmd = new NpgsqlCommand(@"
                INSERT INTO batch_import_jobs (job_id, user_id, user_email, share_url, status, total_videos, total_size)
                VALUES (@jobId, @userId, @userEmail, @shareUrl, 'pending', @totalVideos, @totalSize)
            ", conn))
            {
                cmd.Parameters.AddWithValue("jobId", jobId);
                cmd.Parameters.AddWithValue("userId", userId);
                cmd.Parameters.AddWithValue("userEmail", userEmail);
                cmd.Parameters.AddWithValue("shareUrl", shareUrl);
                cmd.Parameters.AddWithValue("totalVideos", videos.Count);
                cmd.Parameters.AddWithValue("totalSize", totalSize);
                await cmd.ExecuteNonQueryAsync();
            }

            // Create batch import video records
            foreach (var video in videos)
            {
                await using var vidCmd = new NpgsqlCommand(@"
                    INSERT INTO batch_import_videos (job_id, video_name, status, file_size)
                    VALUES (@jobId, @videoName, 'pending', @fileSize)
                ", conn);
                vidCmd.Parameters.AddWithValue("jobId", jobId);
                vidCmd.Parameters.AddWithValue("videoName", video.Name);
                vidCmd.Parameters.AddWithValue("fileSize", video.Size);
                await vidCmd.ExecuteNonQueryAsync();
            }

            // Start background processing
            _ = Task.Run(() => ProcessBatchJobAsync(jobId, userId, userEmail, shareUrl, videos));

            return new Dictionary<string, object?>
            {
                ["job_id"] = jobId,
                ["total_videos"] = videos.Count,
                ["total_size"] = totalSize
            };
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to create batch import job for user {UserId}", userId);
            return null;
        }
    }

    public async Task<Dictionary<string, object?>?> GetBatchJobStatusAsync(string jobId, string userId)
    {
        try
        {
            await using var conn = new NpgsqlConnection(_connectionString);
            await conn.OpenAsync();

            // Get job
            Dictionary<string, object?>? job = null;
            await using (var cmd = new NpgsqlCommand(
                "SELECT * FROM batch_import_jobs WHERE job_id = @jobId AND user_id = @userId", conn))
            {
                cmd.Parameters.AddWithValue("jobId", jobId);
                cmd.Parameters.AddWithValue("userId", userId);
                await using var reader = await cmd.ExecuteReaderAsync();
                if (await reader.ReadAsync())
                {
                    job = new Dictionary<string, object?>();
                    for (var i = 0; i < reader.FieldCount; i++)
                    {
                        var val = reader.GetValue(i);
                        job[reader.GetName(i)] = val is DateTime dt ? dt.ToString("o") : val;
                    }
                }
            }

            if (job == null) return null;

            // Get videos
            var videos = new List<Dictionary<string, object?>>();
            await using (var cmd = new NpgsqlCommand(
                "SELECT * FROM batch_import_videos WHERE job_id = @jobId ORDER BY created_at ASC", conn))
            {
                cmd.Parameters.AddWithValue("jobId", jobId);
                await using var reader = await cmd.ExecuteReaderAsync();
                while (await reader.ReadAsync())
                {
                    var video = new Dictionary<string, object?>();
                    for (var i = 0; i < reader.FieldCount; i++)
                    {
                        var val = reader.GetValue(i);
                        video[reader.GetName(i)] = val is DateTime dt ? dt.ToString("o") : val;
                    }
                    videos.Add(video);
                }
            }

            return new Dictionary<string, object?>
            {
                ["job_id"] = job.GetValueOrDefault("job_id"),
                ["status"] = job.GetValueOrDefault("status"),
                ["total_videos"] = job.GetValueOrDefault("total_videos"),
                ["processed_videos"] = job.GetValueOrDefault("processed_videos"),
                ["failed_videos"] = job.GetValueOrDefault("failed_videos"),
                ["created_at"] = job.GetValueOrDefault("created_at"),
                ["completed_at"] = job.GetValueOrDefault("completed_at"),
                ["videos"] = videos.Select(v => new Dictionary<string, object?>
                {
                    ["video_name"] = v.GetValueOrDefault("video_name"),
                    ["status"] = v.GetValueOrDefault("status"),
                    ["progress_percent"] = v.GetValueOrDefault("progress_percent") ?? 0,
                    ["video_id"] = v.GetValueOrDefault("video_id"),
                    ["error_message"] = v.GetValueOrDefault("error_message")
                }).ToList()
            };
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to get batch job status for {JobId}", jobId);
            return null;
        }
    }

    public async Task<List<Dictionary<string, object?>>> ListUserBatchJobsAsync(string userId, int limit = 20)
    {
        var jobs = new List<Dictionary<string, object?>>();
        try
        {
            await using var conn = new NpgsqlConnection(_connectionString);
            await conn.OpenAsync();
            await using var cmd = new NpgsqlCommand(@"
                SELECT job_id, share_url, status, total_videos, processed_videos, failed_videos, created_at, completed_at
                FROM batch_import_jobs
                WHERE user_id = @userId
                ORDER BY created_at DESC
                LIMIT @limit
            ", conn);
            cmd.Parameters.AddWithValue("userId", userId);
            cmd.Parameters.AddWithValue("limit", limit);

            await using var reader = await cmd.ExecuteReaderAsync();
            while (await reader.ReadAsync())
            {
                var job = new Dictionary<string, object?>();
                for (var i = 0; i < reader.FieldCount; i++)
                {
                    var val = reader.GetValue(i);
                    job[reader.GetName(i)] = val is DateTime dt ? dt.ToString("o") : val;
                }
                jobs.Add(job);
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to list batch jobs for user {UserId}", userId);
        }
        return jobs;
    }

    private async Task<List<(string Name, long Size)>> ListVideosFromShareUrl(string shareUrl)
    {
        var videos = new List<(string Name, long Size)>();
        var validExtensions = new[] { ".mp4", ".avi", ".mov", ".wmv", ".mkv", ".ts", ".m4v", ".flv", ".webm" };

        try
        {
            // Extract share token for authentication
            var shareToken = ExtractShareToken(shareUrl);
            if (string.IsNullOrEmpty(shareToken))
            {
                _logger.LogWarning("Could not extract share token from URL: {ShareUrl}", shareUrl);
                return videos;
            }

            // Convert share URL to WebDAV PROPFIND URL
            var webdavUrl = ConvertToWebDavUrl(shareUrl);

            using var client = _httpClientFactory.CreateClient();
            client.Timeout = TimeSpan.FromSeconds(60);

            var request = new HttpRequestMessage(new HttpMethod("PROPFIND"), webdavUrl);
            request.Headers.Add("Depth", "1");
            
            // Add Basic Authentication with share token as username and empty password
            var authBytes = System.Text.Encoding.ASCII.GetBytes($"{shareToken}:");
            request.Headers.Authorization = new System.Net.Http.Headers.AuthenticationHeaderValue(
                "Basic", Convert.ToBase64String(authBytes));
            
            request.Content = new StringContent(
                "<?xml version=\"1.0\" encoding=\"UTF-8\"?><d:propfind xmlns:d=\"DAV:\"><d:prop><d:getcontentlength/><d:displayname/><d:getcontenttype/></d:prop></d:propfind>",
                System.Text.Encoding.UTF8, "application/xml");

            _logger.LogInformation("Listing videos from WebDAV: {Url} with token: {Token}", webdavUrl, shareToken);

            var response = await client.SendAsync(request);
            if (!response.IsSuccessStatusCode)
            {
                var errorBody = await response.Content.ReadAsStringAsync();
                _logger.LogWarning("WebDAV PROPFIND failed with status {StatusCode} for {Url}. Response: {Response}", 
                    response.StatusCode, webdavUrl, errorBody.Length > 500 ? errorBody[..500] : errorBody);
                return videos;
            }

            var xml = await response.Content.ReadAsStringAsync();

            // Simple XML parsing for filenames and sizes
            var doc = new System.Xml.XmlDocument();
            doc.LoadXml(xml);
            var nsManager = new System.Xml.XmlNamespaceManager(doc.NameTable);
            nsManager.AddNamespace("d", "DAV:");

            var responses = doc.SelectNodes("//d:response", nsManager);
            if (responses != null)
            {
                foreach (System.Xml.XmlNode resp in responses)
                {
                    var href = resp.SelectSingleNode("d:href", nsManager)?.InnerText ?? "";
                    var displayName = resp.SelectSingleNode(".//d:displayname", nsManager)?.InnerText;
                    var contentLength = resp.SelectSingleNode(".//d:getcontentlength", nsManager)?.InnerText;

                    var name = displayName ?? Path.GetFileName(Uri.UnescapeDataString(href));
                    if (string.IsNullOrEmpty(name)) continue;

                    if (validExtensions.Any(ext => name.EndsWith(ext, StringComparison.OrdinalIgnoreCase)))
                    {
                        long.TryParse(contentLength, out var size);
                        videos.Add((name, size));
                    }
                }
            }
            
            _logger.LogInformation("Found {Count} video files in share", videos.Count);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to list videos from share URL: {ShareUrl}", shareUrl);
        }

        return videos;
    }

    private static string? ExtractShareToken(string shareUrl)
    {
        // Extract share token from URL like https://fanusdigital.wolkesicher.de/s/XTNmCZ4Cd5RBg74
        if (shareUrl.Contains("/s/"))
        {
            var parts = shareUrl.Split("/s/");
            if (parts.Length > 1)
            {
                // Remove any path or query parameters after the token
                var token = parts[1].Split('/')[0].Split('?')[0];
                return token;
            }
        }
        return null;
    }

    private static string ConvertToWebDavUrl(string shareUrl)
    {
        // Convert Nextcloud share URL to WebDAV URL
        // e.g., https://cloud.example.com/s/TOKEN -> https://cloud.example.com/public.php/webdav/
        if (shareUrl.Contains("/s/"))
        {
            var parts = shareUrl.Split("/s/");
            var baseUrl = parts[0];
            var token = parts[1].Split('/')[0].Split('?')[0];
            return $"{baseUrl}/public.php/webdav/";
        }
        return shareUrl;
    }

    private async Task ProcessBatchJobAsync(string jobId, string userId, string userEmail, string shareUrl,
        List<(string Name, long Size)> videos)
    {
        try
        {
            // Extract share token for authentication
            var shareToken = ExtractShareToken(shareUrl);
            if (string.IsNullOrEmpty(shareToken))
            {
                _logger.LogError("Could not extract share token from URL for batch job {JobId}", jobId);
                throw new Exception("Invalid share URL - could not extract token");
            }

            await using var conn = new NpgsqlConnection(_connectionString);
            await conn.OpenAsync();

            // Update job status to processing
            await using (var cmd = new NpgsqlCommand(
                "UPDATE batch_import_jobs SET status = 'processing' WHERE job_id = @jobId", conn))
            {
                cmd.Parameters.AddWithValue("jobId", jobId);
                await cmd.ExecuteNonQueryAsync();
            }

            var processed = 0;
            var failed = 0;

            foreach (var video in videos)
            {
                try
                {
                    var videoId = Guid.NewGuid().ToString();

                    // Download and upload video with authentication
                    var downloadUrl = ConvertShareToDownloadUrl(shareUrl, video.Name);
                    
                    using var client = _httpClientFactory.CreateClient();
                    client.Timeout = TimeSpan.FromMinutes(30);
                    
                    // Create request with Basic Authentication
                    var request = new HttpRequestMessage(HttpMethod.Get, downloadUrl);
                    var authBytes = System.Text.Encoding.ASCII.GetBytes($"{shareToken}:");
                    request.Headers.Authorization = new System.Net.Http.Headers.AuthenticationHeaderValue(
                        "Basic", Convert.ToBase64String(authBytes));
                    
                    _logger.LogInformation("Downloading video: {Name} from {Url}", video.Name, downloadUrl);
                    
                    var response = await client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead);
                    response.EnsureSuccessStatusCode();

                    await using var stream = await response.Content.ReadAsStreamAsync();
                    var s3Key = await _s3.UploadVideoAsync(stream, videoId, video.Name);

                    // Create task
                    await _db.CreateVideoTaskAsync(videoId, video.Name, userId, userEmail, "in_queue", s3Key);

                    // Trigger worker to process the video (when Worker API is disabled)
                    await TriggerWorkerAfterUploadAsync(videoId, userId, video.Name, s3Key);

                    // Update batch video record
                    await using (var cmd = new NpgsqlCommand(@"
                        UPDATE batch_import_videos
                        SET video_id = @videoId, status = 'completed', progress_percent = 100, updated_at = CURRENT_TIMESTAMP
                        WHERE job_id = @jobId AND video_name = @videoName AND video_id IS NULL
                    ", conn))
                    {
                        cmd.Parameters.AddWithValue("videoId", videoId);
                        cmd.Parameters.AddWithValue("jobId", jobId);
                        cmd.Parameters.AddWithValue("videoName", video.Name);
                        await cmd.ExecuteNonQueryAsync();
                    }

                    processed++;
                    _logger.LogInformation("Batch import: processed {Name} as {VideoId}", video.Name, videoId);
                }
                catch (Exception ex)
                {
                    failed++;
                    _logger.LogError(ex, "Batch import: failed to process {Name}", video.Name);

                    await using var cmd = new NpgsqlCommand(@"
                        UPDATE batch_import_videos
                        SET status = 'failed', error_message = @error, updated_at = CURRENT_TIMESTAMP
                        WHERE job_id = @jobId AND video_name = @videoName AND video_id IS NULL
                    ", conn);
                    cmd.Parameters.AddWithValue("error", ex.Message);
                    cmd.Parameters.AddWithValue("jobId", jobId);
                    cmd.Parameters.AddWithValue("videoName", video.Name);
                    await cmd.ExecuteNonQueryAsync();
                }

                // Update job progress
                await using (var cmd = new NpgsqlCommand(@"
                    UPDATE batch_import_jobs
                    SET processed_videos = @processed, failed_videos = @failed
                    WHERE job_id = @jobId
                ", conn))
                {
                    cmd.Parameters.AddWithValue("processed", processed);
                    cmd.Parameters.AddWithValue("failed", failed);
                    cmd.Parameters.AddWithValue("jobId", jobId);
                    await cmd.ExecuteNonQueryAsync();
                }
            }

            // Mark job as completed
            await using (var cmd = new NpgsqlCommand(@"
                UPDATE batch_import_jobs
                SET status = 'completed', processed_videos = @processed, failed_videos = @failed, completed_at = CURRENT_TIMESTAMP
                WHERE job_id = @jobId
            ", conn))
            {
                cmd.Parameters.AddWithValue("processed", processed);
                cmd.Parameters.AddWithValue("failed", failed);
                cmd.Parameters.AddWithValue("jobId", jobId);
                await cmd.ExecuteNonQueryAsync();
            }

            _logger.LogInformation("Batch import job {JobId} completed: {Processed} processed, {Failed} failed", jobId, processed, failed);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Batch import job {JobId} failed", jobId);

            try
            {
                await using var conn = new NpgsqlConnection(_connectionString);
                await conn.OpenAsync();
                await using var cmd = new NpgsqlCommand(
                    "UPDATE batch_import_jobs SET status = 'failed', error_message = @error WHERE job_id = @jobId", conn);
                cmd.Parameters.AddWithValue("error", ex.Message);
                cmd.Parameters.AddWithValue("jobId", jobId);
                await cmd.ExecuteNonQueryAsync();
            }
            catch { /* ignore */ }
        }
    }

    private static string ConvertShareToDownloadUrl(string shareUrl, string filename)
    {
        if (shareUrl.Contains("/s/"))
        {
            var parts = shareUrl.Split("/s/");
            var baseUrl = parts[0];
            var token = parts[1].Split('/')[0].Split('?')[0];
            return $"{baseUrl}/public.php/webdav/{Uri.EscapeDataString(filename)}";
        }
        return shareUrl;
    }

    /// <summary>
    /// Trigger worker via HTTP when Worker API is disabled; otherwise workers poll for tasks.
    /// </summary>
    private async Task TriggerWorkerAfterUploadAsync(string videoId, string userId, string filename, string s3Key)
    {
        if (IsWorkerApiEnabled)
        {
            _logger.LogInformation("Worker API enabled - batch task queued for API pickup: {VideoId}", videoId);
            return;
        }

        var payload = new Dictionary<string, object?>
        {
            ["video_id"] = videoId,
            ["user_id"] = userId,
            ["filename"] = filename,
            ["s3_key"] = s3Key
        };

        var result = _workerManager.TriggerWithFallback(payload);
        var success = result.TryGetValue("success", out var ok) && ok is true;

        if (success)
        {
            _logger.LogInformation("Worker triggered successfully for batch video {VideoId}", videoId);
        }
        else
        {
            _logger.LogWarning("Worker trigger failed for batch video {VideoId}: {Error}", videoId, result.GetValueOrDefault("error"));
            await _db.UpdateVideoTaskAsync(videoId, new Dictionary<string, object?>
            {
                ["status"] = "failed",
                ["error_message"] = result.GetValueOrDefault("error")?.ToString() ?? "Worker service unavailable"
            });
        }
    }
}
