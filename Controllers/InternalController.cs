using Microsoft.AspNetCore.Mvc;
using ThakiiBackend.Api.Services;

namespace ThakiiBackend.Api.Controllers;

[ApiController]
[Route("internal")]
public class InternalController : ControllerBase
{
    private readonly IPostgresDbService _db;
    private readonly IEmailNotificationService _emailService;
    private readonly ITaskUpdateHubService _taskUpdateHub;
    private readonly IVideoCreditRefundService _creditRefundService;
    private readonly IConfiguration _config;
    private readonly ILogger<InternalController> _logger;

    public InternalController(
        IPostgresDbService db,
        IEmailNotificationService emailService,
        ITaskUpdateHubService taskUpdateHub,
        IVideoCreditRefundService creditRefundService,
        IConfiguration config,
        ILogger<InternalController> logger)
    {
        _db = db;
        _emailService = emailService;
        _taskUpdateHub = taskUpdateHub;
        _creditRefundService = creditRefundService;
        _config = config;
        _logger = logger;
    }

    private bool IsWorkerApiEnabled =>
        (Environment.GetEnvironmentVariable("ENABLE_WORKER_API") ??
         _config["Worker:EnableWorkerApi"] ?? "false").Equals("true", StringComparison.OrdinalIgnoreCase);

    /// <summary>
    /// Internal endpoint for worker to notify about task updates.
    /// Triggers WebSocket notifications and email notifications.
    /// </summary>
    [HttpPost("task-update")]
    public async Task<IActionResult> TaskUpdate([FromBody] TaskUpdateRequest? request)
    {
        if (request == null || string.IsNullOrEmpty(request.VideoId) ||
            string.IsNullOrEmpty(request.Status) || string.IsNullOrEmpty(request.UserId))
        {
            return BadRequest(new { error = "Missing required fields" });
        }

        try
        {
            var task = await _db.GetVideoTaskAsync(request.VideoId);
            if (task == null)
                return NotFound(new { error = "Task not found" });

            // Send email notification for completed or failed tasks
            var emailAttempted = false;
            if (request.Status is "completed" or "failed" or "done")
            {
                emailAttempted = true;
                try
                {
                    var userEmail = task.GetValueOrDefault("user_email")?.ToString();
                    if (!string.IsNullOrEmpty(userEmail))
                    {
                        var emailStatus = request.Status is "completed" or "done" ? "completed" : "failed";
                        var filename = task.GetValueOrDefault("filename")?.ToString() ?? "Unknown";
                        var errorMessage = emailStatus == "failed" ? task.GetValueOrDefault("error_message")?.ToString() : null;
                        var pdfUrl = emailStatus == "completed" ? task.GetValueOrDefault("pdf_url")?.ToString() : null;

                        _emailService.SendProcessingCompleteNotification(userEmail, request.VideoId, filename, emailStatus, errorMessage, pdfUrl);
                        _logger.LogInformation("Email notification sent to {Email} for video {VideoId}", userEmail, request.VideoId);
                    }
                }
                catch (Exception emailError)
                {
                    _logger.LogError(emailError, "Email notification error for video {VideoId}", request.VideoId);
                }
            }

            // Send WebSocket notification with full task (match Python: websocket_manager.notify_task_update(user_id, task))
            await _taskUpdateHub.NotifyTaskUpdateAsync(request.UserId, task);

            return Ok(new
            {
                success = true,
                message = "Notifications sent",
                websocket_sent = true,
                email_attempted = emailAttempted
            });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error in internal task update for video {VideoId}", request.VideoId);
            return StatusCode(500, new { error = ex.Message });
        }
    }

    /// <summary>
    /// Worker API endpoint to atomically pick up a single task.
    /// </summary>
    [HttpPost("worker/pickup-task")]
    public async Task<IActionResult> PickupTask([FromBody] PickupTaskRequest? request)
    {
        if (!IsWorkerApiEnabled)
            return StatusCode(403, new { error = "Worker API is not enabled" });

        if (request == null || string.IsNullOrEmpty(request.WorkerId))
            return BadRequest(new { error = "worker_id is required" });

        try
        {
            var task = await _db.PickupTaskAsync(request.WorkerId, request.WorkerCapacity);
            if (task != null)
                return Ok(new { success = true, task });

            return NoContent();
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error in worker_pickup_task");
            return StatusCode(500, new { error = ex.Message });
        }
    }

    /// <summary>
    /// Worker API endpoint to update task status.
    /// </summary>
    [HttpPost("worker/update-task")]
    public async Task<IActionResult> UpdateTask([FromBody] UpdateWorkerTaskRequest? request)
    {
        if (!IsWorkerApiEnabled)
            return StatusCode(403, new { error = "Worker API is not enabled" });

        if (request == null || string.IsNullOrEmpty(request.VideoId) ||
            string.IsNullOrEmpty(request.WorkerId) || string.IsNullOrEmpty(request.Status))
        {
            return BadRequest(new { error = "video_id, worker_id, and status are required" });
        }

        try
        {
            if (request.Progress.HasValue)
                _logger.LogInformation("Worker {WorkerId} updating task {VideoId}: {Status} (progress: {Progress}%)",
                    request.WorkerId, request.VideoId, request.Status, request.Progress);
            else
                _logger.LogInformation("Worker {WorkerId} updating task {VideoId}: {Status} (no progress provided)",
                    request.WorkerId, request.VideoId, request.Status);

            var success = await _db.UpdateWorkerTaskAsync(
                request.VideoId, request.WorkerId, request.Status,
                request.Progress, request.PdfUrl, request.ErrorMessage);

            if (success && request.Status == "failed")
            {
                try
                {
                    await _creditRefundService.RefundCreditsForVideoAsync(
                        request.VideoId,
                        request.ErrorMessage ?? "Worker reported failure");
                }
                catch (Exception ex)
                {
                    _logger.LogError(ex, "Refund failed when worker reported failure for video {VideoId}", request.VideoId);
                }
            }

            if (success)
                return Ok(new { success = true });
            return StatusCode(500, new { error = "Failed to update task" });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error in worker_update_task");
            return StatusCode(500, new { error = ex.Message });
        }
    }

    /// <summary>
    /// Worker API endpoint to send heartbeat.
    /// </summary>
    [HttpPost("worker/heartbeat")]
    public IActionResult Heartbeat([FromBody] HeartbeatRequest? request)
    {
        if (!IsWorkerApiEnabled)
            return StatusCode(403, new { error = "Worker API is not enabled" });

        if (request == null || string.IsNullOrEmpty(request.WorkerId))
            return BadRequest(new { error = "worker_id is required" });

        try
        {
            _db.RecordWorkerHeartbeat(request.WorkerId, request.ActiveTaskIds);
            return Ok(new { success = true });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error in worker_heartbeat");
            return StatusCode(500, new { error = ex.Message });
        }
    }

    /// <summary>
    /// Worker API endpoint to recover stale tasks.
    /// </summary>
    [HttpPost("worker/recover-stale-tasks")]
    public async Task<IActionResult> RecoverStaleTasks()
    {
        if (!IsWorkerApiEnabled)
            return StatusCode(403, new { error = "Worker API is not enabled" });

        try
        {
            var count = await _db.RecoverStaleTasksAsync();
            return Ok(new { success = true, recovered_count = count });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error in recover_stale_tasks");
            return StatusCode(500, new { error = ex.Message });
        }
    }

    /// <summary>
    /// Worker API endpoint to check if video cancellation is requested.
    /// </summary>
    [HttpGet("worker/check-cancellation/{videoId}")]
    public async Task<IActionResult> CheckCancellation(string videoId)
    {
        if (!IsWorkerApiEnabled)
            return StatusCode(403, new { error = "Worker API is not enabled" });

        try
        {
            var task = await _db.GetVideoTaskAsync(videoId);
            if (task == null)
                return NotFound(new { error = "Video not found" });

            var cancellationRequested = await _db.IsTaskCancellationRequestedAsync(videoId);

            return Ok(new
            {
                video_id = videoId,
                cancellation_requested = cancellationRequested,
                cancelled = task.GetValueOrDefault("cancelled"),
                status = task.GetValueOrDefault("status"),
                cancellation_reason = task.GetValueOrDefault("cancellation_reason")
            });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error checking cancellation for {VideoId}", videoId);
            return StatusCode(500, new { error = ex.Message });
        }
    }

    /// <summary>
    /// Worker API endpoint to complete video cancellation.
    /// </summary>
    [HttpPost("worker/complete-cancellation/{videoId}")]
    public async Task<IActionResult> CompleteCancellation(string videoId)
    {
        if (!IsWorkerApiEnabled)
            return StatusCode(403, new { error = "Worker API is not enabled" });

        try
        {
            await _db.CompleteCancellationAsync(videoId);
            _logger.LogInformation("Worker completed cancellation for video {VideoId}", videoId);

            return Ok(new
            {
                success = true,
                video_id = videoId,
                message = "Cancellation completed"
            });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error completing cancellation for {VideoId}", videoId);
            return StatusCode(500, new { error = ex.Message });
        }
    }

    /// <summary>
    /// Worker API endpoint to get pending tasks (compatibility endpoint).
    /// </summary>
    [HttpGet("get-pending-tasks")]
    public async Task<IActionResult> GetPendingTasks([FromQuery] int limit = 10)
    {
        if (!IsWorkerApiEnabled)
            return StatusCode(403, new { error = "Worker API is not enabled" });

        try
        {
            var tasks = await _db.GetPendingTasksAsync(limit);
            return Ok(new { success = true, tasks });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error in get_pending_tasks");
            return StatusCode(500, new { error = ex.Message });
        }
    }
}

// Request DTOs for internal endpoints
public class TaskUpdateRequest
{
    public string? VideoId { get; set; }
    public string? Status { get; set; }
    public string? UserId { get; set; }
}

public class PickupTaskRequest
{
    public string? WorkerId { get; set; }
    public int WorkerCapacity { get; set; } = 4;
}

public class UpdateWorkerTaskRequest
{
    public string? VideoId { get; set; }
    public string? WorkerId { get; set; }
    public string? Status { get; set; }
    public int? Progress { get; set; }
    public string? PdfUrl { get; set; }
    public string? ErrorMessage { get; set; }
}

public class HeartbeatRequest
{
    public string? WorkerId { get; set; }
    public List<string>? ActiveTaskIds { get; set; }
}
