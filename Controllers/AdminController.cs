using Microsoft.AspNetCore.Mvc;
using System.Text.RegularExpressions;
using ThakiiBackend.Api.Models;
using ThakiiBackend.Api.Services;

namespace ThakiiBackend.Api.Controllers;

[ApiController]
[Route("admin")]
public class AdminController : ControllerBase
{
    private readonly IPostgresDbService _db;
    private readonly ICustomTokenService _tokenService;
    private readonly IServerManagerService _serverManager;
    private readonly IAdminManagerService _adminManager;
    private readonly IEmailNotificationService _emailService;
    private readonly IPushNotificationService _pushService;
    private readonly IWorkerManagerService _workerManager;
    private readonly IS3StorageService _s3;
    private readonly ILogger<AdminController> _logger;

    public AdminController(
        IPostgresDbService db,
        ICustomTokenService tokenService,
        IServerManagerService serverManager,
        IAdminManagerService adminManager,
        IEmailNotificationService emailService,
        IPushNotificationService pushService,
        IWorkerManagerService workerManager,
        IS3StorageService s3,
        ILogger<AdminController> logger)
    {
        _db = db;
        _tokenService = tokenService;
        _serverManager = serverManager;
        _adminManager = adminManager;
        _emailService = emailService;
        _pushService = pushService;
        _workerManager = workerManager;
        _s3 = s3;
        _logger = logger;
    }

    private CurrentUser? CurrentUser => (CurrentUser?)HttpContext.Items["CurrentUser"];
    private bool IsAdmin => CurrentUser?.IsAdmin == true;
    private bool IsSuperAdmin => CurrentUser != null && _tokenService.IsSuperAdmin(CurrentUser.Email);

    private IActionResult? RequireAdmin()
    {
        if (CurrentUser == null)
            return Unauthorized(new { error = "Authentication required" });
        if (!IsAdmin)
            return StatusCode(403, new { error = "Admin access required", message = "Insufficient privileges" });
        return null;
    }

    private IActionResult? RequireSuperAdmin()
    {
        var adminCheck = RequireAdmin();
        if (adminCheck != null) return adminCheck;
        if (!IsSuperAdmin)
            return StatusCode(403, new { error = "Super admin privileges required" });
        return null;
    }

    // ========== Video Management ==========

    [HttpGet("videos")]
    public async Task<IActionResult> GetVideos()
    {
        var check = RequireAdmin();
        if (check != null) return check;

        try
        {
            var tasks = await _db.GetAllVideoTasksAsync();
            if (tasks.Count == 0) return Ok(Array.Empty<object>());

            var videos = tasks.Select(t => new
            {
                id = t.GetValueOrDefault("video_id") ?? t.GetValueOrDefault("id"),
                video_name = t.GetValueOrDefault("filename"),
                status = t.GetValueOrDefault("status"),
                date = t.GetValueOrDefault("created_at") ?? t.GetValueOrDefault("upload_date"),
                updated_at = t.GetValueOrDefault("updated_at"),
                user_email = t.GetValueOrDefault("user_email"),
                user_id = t.GetValueOrDefault("user_id")
            }).ToList();
            return Ok(videos);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error fetching admin video list");
            return StatusCode(500, new { error = $"Failed to fetch videos: {ex.Message}" });
        }
    }

    [HttpDelete("videos/{videoId}")]
    public async Task<IActionResult> DeleteVideo(string videoId)
    {
        var check = RequireAdmin();
        if (check != null) return check;

        try
        {
            var task = await _db.GetVideoTaskAsync(videoId);
            if (task == null)
                return NotFound(new { error = "Video not found in Firestore" });

            var s3Deletions = new List<string>();

            // Delete from S3: video, subtitle, PDF (match Python admin delete)
            try
            {
                var s3Key = task.GetValueOrDefault("s3_key")?.ToString();
                if (!string.IsNullOrEmpty(s3Key))
                {
                    await _s3.DeleteFileAsync(s3Key);
                    s3Deletions.Add($"video: {s3Key}");
                }
                else
                {
                    var filename = task.GetValueOrDefault("filename")?.ToString();
                    if (!string.IsNullOrEmpty(filename))
                    {
                        var videoKey = $"videos/{videoId}/{System.IO.Path.GetFileName(filename)}";
                        await _s3.DeleteFileAsync(videoKey);
                        s3Deletions.Add($"video: {videoKey}");
                    }
                }

                var subtitleKey = $"subtitles/{videoId}.srt";
                await _s3.DeleteFileAsync(subtitleKey);
                s3Deletions.Add($"subtitle: {subtitleKey}");

                // Match Python admin delete: flat PDF path pdfs/{video_id}.pdf
                var pdfKey = $"pdfs/{videoId}.pdf";
                await _s3.DeleteFileAsync(pdfKey);
                s3Deletions.Add($"pdf: {pdfKey}");
            }
            catch (Exception s3Ex)
            {
                _logger.LogWarning(s3Ex, "S3 deletion warning for video {VideoId}", videoId);
            }

            var deleted = await _db.DeleteVideoTaskAsync(videoId);
            if (!deleted)
                return NotFound(new { error = "Video not found in Firestore" });

            return Ok(new { message = $"Video {videoId} deleted successfully", firestore = "deleted", s3_deletions = s3Deletions });
        }
        catch (Exception ex)
        {
            return StatusCode(500, new { error = $"Failed to delete video: {ex.Message}" });
        }
    }

    [HttpGet("stats")]
    public async Task<IActionResult> GetStats()
    {
        var check = RequireAdmin();
        if (check != null) return check;

        try
        {
            var stats = await _db.GetAdminStatsAsync();
            return Ok(stats);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error fetching admin stats");
            return StatusCode(500, new { error = $"Failed to fetch stats: {ex.Message}" });
        }
    }

    // ========== Stuck Task Recovery (Phase B7+B9) ==========

    /// <summary>
    /// Manually requeue a single video. Forces status back to 'in_queue',
    /// clears the worker columns, and bumps the attempts counter.
    /// </summary>
    [HttpPost("videos/{videoId}/requeue")]
    public async Task<IActionResult> RequeueVideo(string videoId)
    {
        var check = RequireAdmin();
        if (check != null) return check;

        if (string.IsNullOrWhiteSpace(videoId))
            return BadRequest(new { error = "video_id is required" });

        try
        {
            var actor = CurrentUser?.Email ?? "admin";
            var ok = await _db.RequeueVideoAsync(videoId, actor);
            if (!ok) return NotFound(new { error = "video_id not found" });

            _logger.LogWarning("Admin {Actor} requeued video {VideoId}", actor, videoId);
            return Ok(new { success = true, video_id = videoId, requeued_by = actor });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error requeueing video {VideoId}", videoId);
            return StatusCode(500, new { error = ex.Message });
        }
    }

    /// <summary>
    /// Force a reaper sweep right now. Useful in incidents and for tests.
    /// Honors the same Reaper:* configuration as the background service.
    /// </summary>
    [HttpPost("videos/requeue-stuck")]
    public async Task<IActionResult> RequeueStuck([FromServices] IConfiguration cfg)
    {
        var check = RequireAdmin();
        if (check != null) return check;

        try
        {
            var heartbeatStale = TimeSpan.FromSeconds(int.TryParse(
                Environment.GetEnvironmentVariable("REAPER__HEARTBEAT_STALE_SECONDS")
                ?? cfg["Reaper:HeartbeatStaleSeconds"], out var hs) ? hs : 300);
            var noHeartbeatGrace = TimeSpan.FromSeconds(int.TryParse(
                Environment.GetEnvironmentVariable("REAPER__NO_HEARTBEAT_GRACE_SECONDS")
                ?? cfg["Reaper:NoHeartbeatGraceSeconds"], out var ng) ? ng : 900);
            var maxAttempts = int.TryParse(
                Environment.GetEnvironmentVariable("REAPER__MAX_ATTEMPTS")
                ?? cfg["Reaper:MaxAttempts"], out var ma) ? Math.Max(ma, 1) : 3;

            var results = await _db.RequeueStaleProcessingAsync(heartbeatStale, noHeartbeatGrace, maxAttempts);
            var requeued = results.Count(r => r.Action == "requeued");
            var failed = results.Count(r => r.Action == "failed");

            _logger.LogWarning(
                "Manual reaper sweep by {Actor}: total={Total}, requeued={Requeued}, failed={Failed}",
                CurrentUser?.Email ?? "admin", results.Count, requeued, failed);

            return Ok(new
            {
                success = true,
                total = results.Count,
                requeued,
                failed,
                rows = results.Select(r => new { video_id = r.VideoId, attempts = r.Attempts, action = r.Action })
            });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error forcing reaper sweep");
            return StatusCode(500, new { error = ex.Message });
        }
    }

    /// <summary>
    /// Stuck-task buckets used for monitoring / dashboards.
    /// Returns counts that should hover near zero in healthy steady state.
    /// </summary>
    [HttpGet("metrics/stuck-tasks")]
    public async Task<IActionResult> GetStuckTaskMetrics()
    {
        var check = RequireAdmin();
        if (check != null) return check;

        try
        {
            var metrics = await _db.GetStuckTaskMetricsAsync();
            return Ok(metrics);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error fetching stuck task metrics");
            return StatusCode(500, new { error = ex.Message });
        }
    }

    /// <summary>
    /// Phase 8: per-stage timing breakdown for a single video.
    /// </summary>
    [HttpGet("videos/{videoId}/timeline")]
    public async Task<IActionResult> GetVideoTimeline(string videoId)
    {
        var check = RequireAdmin();
        if (check != null) return check;

        try
        {
            var task = await _db.GetVideoTaskAsync(videoId);
            if (task == null)
                return NotFound(new { error = "Video not found" });

            return Ok(new
            {
                video_id = videoId,
                status = task.GetValueOrDefault("status"),
                created_at = task.GetValueOrDefault("created_at"),
                processing_start = task.GetValueOrDefault("processing_start"),
                processing_end = task.GetValueOrDefault("processing_end"),
                progress_phase = task.GetValueOrDefault("progress_phase"),
                progress_percent = task.GetValueOrDefault("progress_percent"),
                attempts = task.GetValueOrDefault("attempts"),
                last_failure_reason = task.GetValueOrDefault("last_failure_reason"),
                video_duration_seconds = task.GetValueOrDefault("video_duration_seconds"),
                stage_timings = new
                {
                    download_seconds = task.GetValueOrDefault("download_seconds"),
                    audio_seconds = task.GetValueOrDefault("audio_seconds"),
                    frames_seconds = task.GetValueOrDefault("frames_seconds"),
                    transcribe_seconds = task.GetValueOrDefault("transcribe_seconds"),
                    pdf_seconds = task.GetValueOrDefault("pdf_seconds"),
                    upload_seconds = task.GetValueOrDefault("upload_seconds"),
                },
                last_heartbeat = task.GetValueOrDefault("last_heartbeat"),
                last_forward_progress_at = task.GetValueOrDefault("last_forward_progress_at"),
                assigned_worker_id = task.GetValueOrDefault("assigned_worker_id"),
            });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error fetching timeline for {VideoId}", videoId);
            return StatusCode(500, new { error = ex.Message });
        }
    }

    // ========== Test Notification ==========

    [HttpPost("test-notification")]
    public IActionResult SendTestNotification([FromBody] TestNotificationRequest? request)
    {
        var check = RequireAdmin();
        if (check != null) return check;

        try
        {
            var testType = request?.Type ?? "simple";
            var result = _pushService.SendTestNotification(testType);

            if (result.GetValueOrDefault("success") is true)
                return Ok(new { message = "Test notification sent successfully", result });
            return StatusCode(500, new { error = "Failed to send test notification", result });
        }
        catch (Exception ex)
        {
            return StatusCode(500, new { error = $"Failed to send test notification: {ex.Message}" });
        }
    }

    // ========== Server Management ==========

    [HttpGet("servers")]
    public IActionResult GetServers()
    {
        var check = RequireAdmin();
        if (check != null) return check;

        try
        {
            var servers = _serverManager.GetAllServers();
            return Ok(servers);
        }
        catch (Exception ex)
        {
            return StatusCode(500, new { error = $"Failed to fetch servers: {ex.Message}" });
        }
    }

    [HttpPost("servers")]
    public IActionResult AddServer([FromBody] AddServerRequest? request)
    {
        var check = RequireAdmin();
        if (check != null) return check;

        if (request == null)
            return BadRequest(new { error = "Request body is required" });
        if (string.IsNullOrEmpty(request.Name))
            return BadRequest(new { error = "Field \"name\" is required" });
        if (string.IsNullOrEmpty(request.Url))
            return BadRequest(new { error = "Field \"url\" is required" });

        try
        {
            var result = _serverManager.AddServer(request.Name, request.Url, request.Type ?? "processing", request.Description ?? "");
            if (result.GetValueOrDefault("success") is true)
                return Ok(result);
            return BadRequest(result);
        }
        catch (Exception ex)
        {
            return StatusCode(500, new { error = $"Failed to add server: {ex.Message}" });
        }
    }

    [HttpPut("servers/{serverId}")]
    public IActionResult UpdateServer(string serverId, [FromBody] Dictionary<string, object?>? updates)
    {
        var check = RequireAdmin();
        if (check != null) return check;

        if (updates == null)
            return BadRequest(new { error = "Request body is required" });

        try
        {
            var result = _serverManager.UpdateServer(serverId, updates);
            if (result.GetValueOrDefault("success") is true)
                return Ok(result);
            return BadRequest(result);
        }
        catch (Exception ex)
        {
            return StatusCode(500, new { error = $"Failed to update server: {ex.Message}" });
        }
    }

    [HttpDelete("servers/{serverId}")]
    public IActionResult RemoveServer(string serverId)
    {
        var check = RequireAdmin();
        if (check != null) return check;

        try
        {
            var result = _serverManager.RemoveServer(serverId);
            if (result.GetValueOrDefault("success") is true)
                return Ok(result);
            return NotFound(result);
        }
        catch (Exception ex)
        {
            return StatusCode(500, new { error = $"Failed to remove server: {ex.Message}" });
        }
    }

    [HttpPost("servers/health-check")]
    public IActionResult CheckServersHealth()
    {
        var check = RequireAdmin();
        if (check != null) return check;

        try
        {
            var result = _serverManager.CheckAllServersHealth();
            return Ok(result);
        }
        catch (Exception ex)
        {
            return StatusCode(500, new { error = $"Failed to check servers health: {ex.Message}" });
        }
    }

    // ========== Admin User Management ==========

    [HttpGet("admins")]
    public IActionResult GetAdmins()
    {
        var check = RequireAdmin();
        if (check != null) return check;

        try
        {
            var admins = _adminManager.GetAllAdmins();
            return Ok(admins);
        }
        catch (Exception ex)
        {
            return StatusCode(500, new { error = $"Failed to fetch admins: {ex.Message}" });
        }
    }

    [HttpPost("admins")]
    public IActionResult AddAdmin([FromBody] AddAdminRequest? request)
    {
        var superCheck = RequireSuperAdmin();
        if (superCheck != null) return superCheck;

        if (request == null)
            return BadRequest(new { error = "Request body is required" });
        if (string.IsNullOrEmpty(request.Email))
            return BadRequest(new { error = "Email is required" });

        try
        {
            var result = _adminManager.AddAdmin(request.Email, request.Role ?? "admin", CurrentUser!.Email!, request.Description ?? "");
            if (result.GetValueOrDefault("success") is true)
                return Ok(result);
            return BadRequest(result);
        }
        catch (Exception ex)
        {
            return StatusCode(500, new { error = $"Failed to add admin: {ex.Message}" });
        }
    }

    [HttpPut("admins/{adminId}")]
    public IActionResult UpdateAdmin(string adminId, [FromBody] Dictionary<string, object?>? updates)
    {
        var superCheck = RequireSuperAdmin();
        if (superCheck != null) return superCheck;

        if (updates == null)
            return BadRequest(new { error = "Request body is required" });

        try
        {
            var result = _adminManager.UpdateAdmin(adminId, updates, CurrentUser!.Email!);
            if (result.GetValueOrDefault("success") is true)
                return Ok(result);
            return BadRequest(result);
        }
        catch (Exception ex)
        {
            return StatusCode(500, new { error = $"Failed to update admin: {ex.Message}" });
        }
    }

    [HttpDelete("admins/{adminId}")]
    public IActionResult RemoveAdmin(string adminId)
    {
        var superCheck = RequireSuperAdmin();
        if (superCheck != null) return superCheck;

        try
        {
            var result = _adminManager.RemoveAdmin(adminId, CurrentUser!.Email!);
            if (result.GetValueOrDefault("success") is true)
                return Ok(result);
            return NotFound(result);
        }
        catch (Exception ex)
        {
            return StatusCode(500, new { error = $"Failed to remove admin: {ex.Message}" });
        }
    }

    [HttpGet("admins/stats")]
    public IActionResult GetAdminUserStats()
    {
        var check = RequireAdmin();
        if (check != null) return check;

        try
        {
            var stats = _adminManager.GetAdminStats();
            return Ok(stats);
        }
        catch (Exception ex)
        {
            return StatusCode(500, new { error = $"Failed to get admin stats: {ex.Message}" });
        }
    }

    // ========== Email Management ==========

    [HttpPost("email/test")]
    public IActionResult TestEmail([FromBody] TestEmailRequest? request)
    {
        var check = RequireAdmin();
        if (check != null) return check;

        if (request == null || string.IsNullOrEmpty(request.Recipient))
            return BadRequest(new { error = "Recipient email required" });

        try
        {
            var success = _emailService.SendTestEmail(request.Recipient);
            if (success)
                return Ok(new { success = true, message = $"Test email sent to {request.Recipient}" });
            return StatusCode(500, new { success = false, message = "Failed to send test email. Check email configuration." });
        }
        catch (Exception ex)
        {
            return StatusCode(500, new { error = $"Email test failed: {ex.Message}" });
        }
    }

    [HttpGet("email/config")]
    public IActionResult GetEmailConfig()
    {
        var check = RequireAdmin();
        if (check != null) return check;

        try
        {
            return Ok(new
            {
                configured = _emailService.IsConfigured,
                service_type = "Brevo API",
                api_url = _emailService.ApiUrl,
                from_email = _emailService.FromEmail,
                from_name = _emailService.FromName,
                additional_recipients = _emailService.AdditionalRecipients,
                has_api_key = _emailService.IsConfigured,
                api_key_preview = _emailService.ApiKeyPreview
            });
        }
        catch (Exception ex)
        {
            return StatusCode(500, new { error = $"Failed to get email config: {ex.Message}" });
        }
    }

    [HttpPost("email/recipients")]
    public IActionResult UpdateRecipients([FromBody] UpdateRecipientsRequest? request)
    {
        var check = RequireAdmin();
        if (check != null) return check;

        if (request == null)
            return BadRequest(new { error = "Request body is required" });

        try
        {
            var emailPattern = new Regex(@"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$");
            var validEmails = new List<string>();

            foreach (var email in request.Emails ?? new List<string>())
            {
                var trimmed = email.Trim();
                if (!emailPattern.IsMatch(trimmed))
                    return BadRequest(new { error = $"Invalid email address: {email}" });
                validEmails.Add(trimmed);
            }

            var success = _emailService.UpdateAdditionalRecipientsInDb(validEmails);
            if (!success)
                return StatusCode(500, new { error = "Failed to save recipients to database" });

            return Ok(new { success = true, message = "Updated notification recipients", recipients = validEmails });
        }
        catch (Exception ex)
        {
            return StatusCode(500, new { error = $"Failed to update recipients: {ex.Message}" });
        }
    }

    [HttpPost("email/recipients/add")]
    public IActionResult AddRecipient([FromBody] SingleRecipientRequest? request)
    {
        var check = RequireAdmin();
        if (check != null) return check;

        if (request == null || string.IsNullOrEmpty(request.Email))
            return BadRequest(new { error = "Email address is required" });

        var emailPattern = new Regex(@"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$");
        var newEmail = request.Email.Trim();

        if (!emailPattern.IsMatch(newEmail))
            return BadRequest(new { error = $"Invalid email address: {newEmail}" });

        try
        {
            var currentRecipients = _emailService.GetAdditionalRecipientsFromDb();

            if (currentRecipients.Contains(newEmail))
                return BadRequest(new { error = $"Email {newEmail} is already in the recipients list" });

            var updatedRecipients = currentRecipients.Concat(new[] { newEmail }).ToList();
            var success = _emailService.UpdateAdditionalRecipientsInDb(updatedRecipients);

            if (!success)
                return StatusCode(500, new { error = "Failed to save recipient to database" });

            return Ok(new { success = true, message = $"Added {newEmail} to notification recipients", recipients = updatedRecipients });
        }
        catch (Exception ex)
        {
            return StatusCode(500, new { error = $"Failed to add recipient: {ex.Message}" });
        }
    }

    [HttpPost("email/recipients/remove")]
    public IActionResult RemoveRecipient([FromBody] SingleRecipientRequest? request)
    {
        var check = RequireAdmin();
        if (check != null) return check;

        if (request == null || string.IsNullOrEmpty(request.Email))
            return BadRequest(new { error = "Email address is required" });

        var emailToRemove = request.Email.Trim();

        try
        {
            var currentRecipients = _emailService.GetAdditionalRecipientsFromDb();

            if (!currentRecipients.Contains(emailToRemove))
                return NotFound(new { error = $"Email {emailToRemove} is not in the recipients list" });

            var updatedRecipients = currentRecipients.Where(e => e != emailToRemove).ToList();
            var success = _emailService.UpdateAdditionalRecipientsInDb(updatedRecipients);

            if (!success)
                return StatusCode(500, new { error = "Failed to save changes to database" });

            return Ok(new { success = true, message = $"Removed {emailToRemove} from notification recipients", recipients = updatedRecipients });
        }
        catch (Exception ex)
        {
            return StatusCode(500, new { error = $"Failed to remove recipient: {ex.Message}" });
        }
    }

    [HttpGet("email/recipients")]
    public IActionResult GetRecipients()
    {
        var check = RequireAdmin();
        if (check != null) return check;

        try
        {
            var recipients = _emailService.GetAdditionalRecipientsFromDb();
            return Ok(new { success = true, recipients, count = recipients.Count });
        }
        catch (Exception ex)
        {
            return StatusCode(500, new { error = $"Failed to get recipients: {ex.Message}" });
        }
    }

    // ========== Worker Health (top-level route: /worker-health) ==========

    [HttpGet("/worker-health")]
    public IActionResult CheckWorkerHealth()
    {
        var check = RequireAdmin();
        if (check != null) return check;

        try
        {
            var healthData = _workerManager.GetAllWorkersHealth();

            var summary = healthData.GetValueOrDefault("summary") as Dictionary<string, object?>;
            var healthyCount = summary?.GetValueOrDefault("healthy_workers") as int? ?? 0;
            var totalCount = summary?.GetValueOrDefault("total_workers") as int? ?? 0;

            string overallStatus;
            int statusCode;

            if (healthyCount == 0)
            {
                overallStatus = "critical";
                statusCode = 503;
            }
            else if (healthyCount < totalCount)
            {
                overallStatus = "degraded";
                statusCode = 200;
            }
            else
            {
                overallStatus = "healthy";
                statusCode = 200;
            }

            return StatusCode(statusCode, new
            {
                overall_status = overallStatus,
                workers = healthData.GetValueOrDefault("workers"),
                summary = healthData.GetValueOrDefault("summary"),
                priority_mode = healthData.GetValueOrDefault("priority_mode"),
                timestamp = healthData.GetValueOrDefault("timestamp")
            });
        }
        catch (Exception ex)
        {
            return StatusCode(500, new
            {
                overall_status = "error",
                error = ex.Message,
                timestamp = DateTime.UtcNow.ToString("o")
            });
        }
    }
}

// ========== Request DTOs ==========

public class TestNotificationRequest
{
    public string? Type { get; set; }
}

public class AddServerRequest
{
    public string? Name { get; set; }
    public string? Url { get; set; }
    public string? Type { get; set; }
    public string? Description { get; set; }
}

public class AddAdminRequest
{
    public string? Email { get; set; }
    public string? Role { get; set; }
    public string? Description { get; set; }
}

public class TestEmailRequest
{
    public string? Recipient { get; set; }
}

public class UpdateRecipientsRequest
{
    public List<string>? Emails { get; set; }
}

public class SingleRecipientRequest
{
    public string? Email { get; set; }
}
