using Microsoft.AspNetCore.Mvc;
using ThakiiBackend.Api.Models;
using ThakiiBackend.Api.Services;

namespace ThakiiBackend.Api.Controllers;

[ApiController]
[Route("batch-import")]
public class BatchImportController : ControllerBase
{
    private readonly IBatchImportService _batchImportService;
    private readonly ICustomTokenService _tokenService;
    private readonly ILogger<BatchImportController> _logger;

    public BatchImportController(
        IBatchImportService batchImportService,
        ICustomTokenService tokenService,
        ILogger<BatchImportController> logger)
    {
        _batchImportService = batchImportService;
        _tokenService = tokenService;
        _logger = logger;
    }

    private CurrentUser? CurrentUser => (CurrentUser?)HttpContext.Items["CurrentUser"];

    /// <summary>
    /// Submit a batch import job.
    /// </summary>
    [HttpPost("submit")]
    public async Task<IActionResult> Submit([FromBody] BatchImportSubmitRequest? request)
    {
        if (CurrentUser == null)
            return Unauthorized(new { error = "Authentication required" });

        if (request == null || string.IsNullOrEmpty(request.ShareUrl))
            return BadRequest(new { error = "share_url is required" });

        // Validate URL format
        if (!request.ShareUrl.StartsWith("http://") && !request.ShareUrl.StartsWith("https://"))
            return BadRequest(new { error = "Invalid share URL format. Must start with http:// or https://" });

        // Validate that URL contains share token pattern
        if (!request.ShareUrl.Contains("/s/"))
            return BadRequest(new { error = "Invalid share URL format. Expected Nextcloud share URL with /s/ pattern" });

        try
        {
            _logger.LogInformation("Batch import request from {Email}, Share URL: {ShareUrl}", CurrentUser.Email, request.ShareUrl);

            var jobResult = await _batchImportService.CreateBatchJobAsync(CurrentUser.Uid!, CurrentUser.Email!, request.ShareUrl);

            if (jobResult == null)
            {
                _logger.LogWarning("Batch import failed for {Email} - no videos found or access denied", CurrentUser.Email);
                return BadRequest(new
                {
                    error = "Failed to create batch import job. No video files found in the share or access denied. Please check that the share URL is correct and contains video files."
                });
            }

            _logger.LogInformation("Created batch job: {JobId} with {TotalVideos} videos", 
                jobResult.GetValueOrDefault("job_id"), jobResult.GetValueOrDefault("total_videos"));

            return Ok(new
            {
                success = true,
                job_id = jobResult.GetValueOrDefault("job_id"),
                total_videos = jobResult.GetValueOrDefault("total_videos"),
                total_size = jobResult.GetValueOrDefault("total_size")
            });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error in submit_batch_import for {Email}", CurrentUser.Email);
            return StatusCode(500, new { error = $"Internal server error: {ex.Message}" });
        }
    }

    /// <summary>
    /// Get status of a batch import job.
    /// </summary>
    [HttpGet("status/{jobId}")]
    public async Task<IActionResult> GetStatus(string jobId)
    {
        if (CurrentUser == null)
            return Unauthorized(new { error = "Authentication required" });

        try
        {
            var jobStatus = await _batchImportService.GetBatchJobStatusAsync(jobId, CurrentUser.Uid!);

            if (jobStatus == null)
                return NotFound(new { error = "Batch job not found" });

            return Ok(jobStatus);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error in get_batch_import_status for {JobId}", jobId);
            return StatusCode(500, new { error = "Internal server error" });
        }
    }

    /// <summary>
    /// List batch import jobs for the current user.
    /// </summary>
    [HttpGet("jobs")]
    public async Task<IActionResult> ListJobs([FromQuery] int limit = 20)
    {
        if (CurrentUser == null)
            return Unauthorized(new { error = "Authentication required" });

        try
        {
            if (limit < 1 || limit > 100) limit = 20;

            var jobs = await _batchImportService.ListUserBatchJobsAsync(CurrentUser.Uid!, limit);
            return Ok(new { jobs });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error in list_batch_import_jobs");
            return StatusCode(500, new { error = "Internal server error" });
        }
    }
}

public class BatchImportSubmitRequest
{
    public string? ShareUrl { get; set; }
}
