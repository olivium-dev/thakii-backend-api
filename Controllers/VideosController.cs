using Microsoft.AspNetCore.Mvc;
using System.Diagnostics;
using System.Globalization;
using ThakiiBackend.Api.Models;
using ThakiiBackend.Api.Services;
using thakii.service.ServiceWallet;

namespace ThakiiBackend.Api.Controllers;

[ApiController]
[Route("")]
public class VideosController : ControllerBase
{
    private readonly IPostgresDbService _db;
    private readonly IS3StorageService _s3;
    private readonly ICustomTokenService _tokenService;
    private readonly IVideoPricingService _videoPricingService;
    private readonly ServiceWalletClient _walletClient;
    private readonly IVideoCatalogService _videoCatalogService;
    private readonly IWorkerManagerService _workerManager;
    private readonly ITaskUpdateHubService _taskUpdateHub;
    private readonly IConfiguration _config;
    private readonly ILogger<VideosController> _logger;

    public VideosController(
        IPostgresDbService db,
        IS3StorageService s3,
        ICustomTokenService tokenService,
        IVideoPricingService videoPricingService,
        ServiceWalletClient walletClient,
        IVideoCatalogService videoCatalogService,
        IWorkerManagerService workerManager,
        ITaskUpdateHubService taskUpdateHub,
        IConfiguration config,
        ILogger<VideosController> logger)
    {
        _db = db;
        _s3 = s3;
        _tokenService = tokenService;
        _videoPricingService = videoPricingService;
        _walletClient = walletClient;
        _videoCatalogService = videoCatalogService;
        _workerManager = workerManager;
        _taskUpdateHub = taskUpdateHub;
        _config = config;
        _logger = logger;
    }

    private bool IsWorkerApiEnabled =>
        (Environment.GetEnvironmentVariable("ENABLE_WORKER_API") ?? _config["Worker:EnableWorkerApi"] ?? "false")
        .Equals("true", StringComparison.OrdinalIgnoreCase);

    /// <summary>
    /// Trigger worker via HTTP when Worker API is disabled; otherwise workers poll for tasks.
    /// </summary>
    private async Task TriggerWorkerAfterUploadAsync(string videoId, string userId, string filename, string s3Key)
    {
        if (IsWorkerApiEnabled)
        {
            _logger.LogInformation("Worker API enabled - task queued for API pickup: {VideoId}", videoId);
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
            _logger.LogInformation("Worker triggered successfully for {VideoId}", videoId);
        else
        {
            _logger.LogWarning("Worker trigger failed for {VideoId}: {Error}", videoId, result.GetValueOrDefault("error"));
            await _db.UpdateVideoTaskAsync(videoId, new Dictionary<string, object?>
            {
                ["status"] = "failed",
                ["error_message"] = result.GetValueOrDefault("error")?.ToString() ?? "Worker service unavailable"
            });
        }
    }

    private CurrentUser? CurrentUser => (CurrentUser?)HttpContext.Items["CurrentUser"];
    private bool IsSuperAdmin => CurrentUser != null && _tokenService.IsSuperAdmin(CurrentUser.Email);

    // Same holderId logic as AuthController: map Firebase uid -> deterministic GUID for wallet service
    private static Guid UidToHolderId(string uid)
    {
        using var md5 = System.Security.Cryptography.MD5.Create();
        var bytes = System.Text.Encoding.UTF8.GetBytes(uid);
        var hash = md5.ComputeHash(bytes);
        return new Guid(hash);
    }

    [HttpPost("upload")]
    public async Task<IActionResult> Upload(IFormFile? file)
    {
        if (CurrentUser == null)
            return Unauthorized(new { error = "Authentication required" });
        if (file == null || file.Length == 0)
            return BadRequest(new { error = "No file provided" });
        if (string.IsNullOrEmpty(file.FileName))
            return BadRequest(new { error = "No selected file" });

        // Save to a temporary file so we can both analyze duration and upload to S3
        var videoId = Guid.NewGuid().ToString();
        var filename = file.FileName;
        var tempPath = Path.Combine(Path.GetTempPath(), $"{videoId}{Path.GetExtension(filename)}");

        try
        {
            await using (var fs = System.IO.File.Create(tempPath))
            {
                await file.CopyToAsync(fs);
            }

            // Detect video duration (in minutes) from the actual file using ffprobe
            var durationMinutes = GetVideoDurationMinutes(tempPath);
            if (durationMinutes <= 0)
            {
                _logger.LogWarning("Failed to detect duration for uploaded video {VideoId} (file {FileName}).", videoId, filename);
                return BadRequest(new { error = "Unable to determine video duration from the uploaded file" });
            }

            // Calculate required credits based on duration and pricing config
            var creditsNeeded = _videoPricingService.CalculateCreditsForMinutes(durationMinutes);
            var minutesPerCredit = _videoPricingService.GetMinutesPerCredit();

            var holderId = UidToHolderId(CurrentUser.Uid!);

            // Check user wallet balance before accepting upload
            try
            {
                var userWalletHolder = await _walletClient.WalletsAsync(holderId);
                if (userWalletHolder.WalletHolder == null || userWalletHolder.Wallets == null || !userWalletHolder.Wallets.Any())
                    return StatusCode(402, new { error = "User wallet not found", required_credits = creditsNeeded });

                var userCreditWallet = userWalletHolder.Wallets.FirstOrDefault(w => w.CurrencyID == 1);
                if (userCreditWallet == null)
                    return StatusCode(402, new { error = "User credit wallet not found", required_credits = creditsNeeded });

                var userBalance = (decimal)userCreditWallet.Amount;
                var requiredCreditsDecimal = (decimal)creditsNeeded;

                if (userBalance < requiredCreditsDecimal)
                {
                    return StatusCode(402, new
                    {
                        error = "Insufficient credits for this video upload",
                        duration_minutes = durationMinutes,
                        minutes_per_credit = minutesPerCredit,
                        required_credits = creditsNeeded,
                        available_credits = userBalance
                    });
                }
            }
            catch (ApiException ex)
            {
                _logger.LogError(ex, "Wallet API error while checking credits for upload for user {UserId}", CurrentUser.Uid);
                return StatusCode(ex.StatusCode, new { error = "Wallet API error while checking credits", details = ex.Message });
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Unexpected error while checking credits for upload for user {UserId}", CurrentUser.Uid);
                return StatusCode(500, new { error = "Unexpected error while checking credits", details = ex.Message });
            }

            await using var uploadStream = System.IO.File.OpenRead(tempPath);
            var s3Key = await _s3.UploadVideoAsync(uploadStream, videoId, filename);
            await _db.CreateVideoTaskAsync(videoId, filename, CurrentUser.Uid!, CurrentUser.Email!, "in_queue", s3Key);

            // Deduct credits after successful upload: user credit wallet -> system wallet
            try
            {
                var userWalletHolder = await _walletClient.WalletsAsync(holderId);
                var userCreditWallet = userWalletHolder.Wallets?.FirstOrDefault(w => w.CurrencyID == 1);
                var systemWallet = await _walletClient.SystemWalletAsync();
                var systemCreditWalletId = systemWallet.Wallets?.FirstOrDefault(w => w.Type == "__SYSTEM__")?.WalletId;

                if (userCreditWallet != null && systemCreditWalletId != null && creditsNeeded > 0)
                {
                    var transaction = new TransactionRequest
                    {
                        ServiceName = "ThakiiVideoService",
                        Tag = $"VideoUpload-{videoId}",
                        Notes = $"Credit deduction for video upload {videoId}, duration {durationMinutes} minutes",
                        Transactions = new List<TransactionDetailsRequest>
                        {
                            new TransactionDetailsRequest
                            {
                                SourceWalletId = userCreditWallet.WalletId,
                                DestinationWalletId = (Guid)systemCreditWalletId,
                                Amount = (double)creditsNeeded
                            }
                        }
                    };
                    var txResult = await _walletClient.InitiateAsync(transaction);
                    await _walletClient.ExecuteAsync(txResult.TransactionHeader.TxId);
                    _logger.LogInformation("Deducted {Credits} credits for upload {VideoId}. TxId={TxId}", creditsNeeded, videoId, txResult.TransactionHeader.TxId);
                }
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to deduct credits after upload {VideoId}. Video and task were created; consider manual adjustment.", videoId);
                return StatusCode(500, new
                {
                    error = "Upload succeeded but credit deduction failed",
                    video_id = videoId,
                    details = ex.Message,
                    required_credits = creditsNeeded
                });
            }

            await TriggerWorkerAfterUploadAsync(videoId, CurrentUser.Uid!, filename, s3Key);

            await _taskUpdateHub.NotifyTaskUpdateAsync(CurrentUser.Uid!, new { video_id = videoId, status = "in_queue", filename });

            return Ok(new
            {
                video_id = videoId,
                duration_minutes = durationMinutes,
                credits_deducted = creditsNeeded,
                message = "Video uploaded and credits deducted",
                s3_key = s3Key,
                mode = IsWorkerApiEnabled ? "worker_api" : "http_trigger"
            });
        }
        finally
        {
            try
            {
                if (System.IO.File.Exists(tempPath))
                {
                    System.IO.File.Delete(tempPath);
                }
            }
            catch
            {
                // If cleanup fails, we just ignore it.
            }
        }
    }

    /// <summary>
    /// Uses ffprobe (must be installed and available in PATH) to detect video duration in minutes.
    /// </summary>
    private static double GetVideoDurationMinutes(string filePath)
    {
        var startInfo = new ProcessStartInfo
        {
            FileName = "ffprobe",
            Arguments = $"-v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 \"{filePath}\"",
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true
        };

        try
        {
            using var process = Process.Start(startInfo);
            if (process == null)
            {
                return 0;
            }

            var output = process.StandardOutput.ReadToEnd();
            var error = process.StandardError.ReadToEnd();
            process.WaitForExit(10000);

            if (process.ExitCode != 0)
            {
                return 0;
            }

            if (double.TryParse(output.Trim(), NumberStyles.Any, CultureInfo.InvariantCulture, out var seconds))
            {
                return seconds / 60.0;
            }

            return 0;
        }
        catch
        {
            return 0;
        }
    }

    /// <summary>
    /// TEMPORARY AUTH BYPASS FOR TESTING - Test upload endpoint.
    /// </summary>
    [HttpPost("test-upload")]
    public async Task<IActionResult> TestUpload(IFormFile? file)
    {
        _logger.LogInformation("TEST UPLOAD: Using auth bypass endpoint");

        if (file == null || file.Length == 0)
            return BadRequest(new { error = "No file provided" });
        if (string.IsNullOrEmpty(file.FileName))
            return BadRequest(new { error = "No selected file" });

        var testUser = new { uid = "test-user-bypass", email = "test@thakii.com" };
        var videoId = Guid.NewGuid().ToString();
        var filename = file.FileName;

        try
        {
            _logger.LogInformation("TEST: Uploading {Filename} as {VideoId}", filename, videoId);
            await using var stream = file.OpenReadStream();
            var s3Key = await _s3.UploadVideoAsync(stream, videoId, filename);

            await _db.CreateVideoTaskAsync(videoId, filename, testUser.uid, testUser.email, "in_queue", s3Key);
            _logger.LogInformation("TEST: Task created in PostgreSQL: {VideoId} for user: {Email}", videoId, testUser.email);

            await TriggerWorkerAfterUploadAsync(videoId, testUser.uid, filename, s3Key);

            await _taskUpdateHub.NotifyTaskUpdateAsync(testUser.uid, new { video_id = videoId, status = "in_queue", filename });

            return Ok(new
            {
                video_id = videoId,
                message = "TEST: Video uploaded to S3 and queued for processing",
                s3_key = s3Key,
                test_mode = true,
                user = testUser,
                mode = IsWorkerApiEnabled ? "worker_api" : "http_trigger"
            });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "TEST: Error uploading video");
            return StatusCode(500, new { error = $"Failed to upload video: {ex.Message}" });
        }
    }

    /// <summary>
    /// Upload a single chunk of a large file.
    /// </summary>
    [HttpPost("upload-chunk")]
    public async Task<IActionResult> UploadChunk()
    {
        if (CurrentUser == null)
            return Unauthorized(new { error = "Authentication required" });

        try
        {
            var chunkIndex = Request.Form["chunk_index"].FirstOrDefault();
            var totalChunks = Request.Form["total_chunks"].FirstOrDefault();
            var fileId = Request.Form["file_id"].FirstOrDefault();
            var originalFilename = Request.Form["original_filename"].FirstOrDefault();

            if (string.IsNullOrEmpty(chunkIndex) || string.IsNullOrEmpty(totalChunks) ||
                string.IsNullOrEmpty(fileId) || string.IsNullOrEmpty(originalFilename))
            {
                return BadRequest(new { error = "Missing chunk metadata" });
            }

            if (!Request.Form.Files.Any() || Request.Form.Files["chunk"] == null)
                return BadRequest(new { error = "No chunk file provided" });

            var chunkFile = Request.Form.Files["chunk"]!;
            if (string.IsNullOrEmpty(chunkFile.FileName))
                return BadRequest(new { error = "No chunk file selected" });

            // Create chunks directory
            var chunksDir = Path.Combine(Path.GetTempPath(), "chunks", fileId);
            Directory.CreateDirectory(chunksDir);

            // Save chunk
            var chunkPath = Path.Combine(chunksDir, $"chunk_{chunkIndex}");
            await using (var fs = System.IO.File.Create(chunkPath))
            {
                await chunkFile.CopyToAsync(fs);
            }

            var chunkSize = new FileInfo(chunkPath).Length;
            _logger.LogInformation("Chunk uploaded: {FileId} - {ChunkIndex}/{TotalChunks}, size: {Size} bytes",
                fileId, chunkIndex, totalChunks, chunkSize);

            return Ok(new
            {
                chunk_index = int.Parse(chunkIndex),
                total_chunks = int.Parse(totalChunks),
                file_id = fileId,
                chunk_size = chunkSize,
                message = $"Chunk {chunkIndex}/{totalChunks} uploaded successfully"
            });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error uploading chunk");
            return StatusCode(500, new { error = $"Failed to upload chunk: {ex.Message}" });
        }
    }

    /// <summary>
    /// Assemble chunks into final file and process.
    /// </summary>
    [HttpPost("assemble-file")]
    public async Task<IActionResult> AssembleFile([FromBody] AssembleFileRequest? request)
    {
        if (CurrentUser == null)
            return Unauthorized(new { error = "Authentication required" });

        if (request == null || string.IsNullOrEmpty(request.FileId) ||
            request.TotalChunks <= 0 || string.IsNullOrEmpty(request.OriginalFilename))
        {
            return BadRequest(new { error = "Missing assembly metadata" });
        }

        try
        {
            var chunksDir = Path.Combine(Path.GetTempPath(), "chunks", request.FileId);
            if (!Directory.Exists(chunksDir))
                return NotFound(new { error = "Chunks directory not found" });

            // Verify all chunks exist
            var missingChunks = new List<int>();
            for (var i = 0; i < request.TotalChunks; i++)
            {
                if (!System.IO.File.Exists(Path.Combine(chunksDir, $"chunk_{i}")))
                    missingChunks.Add(i);
            }

            if (missingChunks.Count > 0)
                return BadRequest(new { error = "Missing chunks", missing_chunks = missingChunks });

            // Assemble file
            var videoId = Guid.NewGuid().ToString();
            var assembledPath = Path.Combine(Path.GetTempPath(), $"{videoId}_{request.OriginalFilename}");

            _logger.LogInformation("Assembling file: {FileId} -> {VideoId}", request.FileId, videoId);

            long totalSize = 0;
            await using (var outFile = System.IO.File.Create(assembledPath))
            {
                for (var i = 0; i < request.TotalChunks; i++)
                {
                    var chunkPath = Path.Combine(chunksDir, $"chunk_{i}");
                    await using var chunkStream = System.IO.File.OpenRead(chunkPath);
                    await chunkStream.CopyToAsync(outFile);
                    _logger.LogInformation("Assembled chunk {Index}/{Total}", i, request.TotalChunks);
                }
                totalSize = outFile.Length;
            }

            _logger.LogInformation("File assembled: {Size} bytes", totalSize);

            // Upload to S3
            string s3Key;
            await using (var fileStream = System.IO.File.OpenRead(assembledPath))
            {
                s3Key = await _s3.UploadVideoAsync(fileStream, videoId, request.OriginalFilename);
            }

            // Create task in DB (match Python: do not store s3_key for assembled files)
            await _db.CreateVideoTaskAsync(videoId, request.OriginalFilename, CurrentUser.Uid!, CurrentUser.Email!, "in_queue", s3Key: null);

            await TriggerWorkerAfterUploadAsync(videoId, CurrentUser.Uid!, request.OriginalFilename, s3Key);

            await _taskUpdateHub.NotifyTaskUpdateAsync(CurrentUser.Uid!, new { video_id = videoId, status = "in_queue", filename = request.OriginalFilename });

            // Cleanup
            try
            {
                Directory.Delete(chunksDir, true);
                System.IO.File.Delete(assembledPath);
            }
            catch (Exception cleanupEx)
            {
                _logger.LogWarning(cleanupEx, "Cleanup warning after assembly");
            }

            return Ok(new
            {
                video_id = videoId,
                message = "File assembled and queued for processing",
                s3_key = s3Key,
                total_size = totalSize
            });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error assembling file");
            return StatusCode(500, new { error = $"Failed to assemble file: {ex.Message}" });
        }
    }

    /// <summary>
    /// Import a single video from a direct URL or Nextcloud share.
    /// </summary>
    [HttpPost("import-url")]
    public IActionResult ImportUrl([FromBody] ImportUrlRequest? request)
    {
        if (CurrentUser == null)
            return Unauthorized(new { error = "Authentication required" });

        if (request == null || string.IsNullOrEmpty(request.Url?.Trim()))
            return BadRequest(new { error = "URL is required" });

        var url = request.Url.Trim();
        if (!url.StartsWith("http://") && !url.StartsWith("https://"))
            return BadRequest(new { error = "Invalid URL format. Must start with http:// or https://" });

        var customFilename = request.Filename?.Trim();
        var filename = !string.IsNullOrEmpty(customFilename) ? customFilename : ExtractFilenameFromUrl(url);

        if (string.IsNullOrEmpty(filename) || !IsValidVideoFilename(filename))
            return BadRequest(new { error = "Invalid video filename. Must be a video file (mp4, avi, mov, wmv, mkv, ts)" });

        var videoId = Guid.NewGuid().ToString();
        var downloadUrl = ConvertToDirectUrl(url);
        var userId = CurrentUser.Uid!;
        var userEmail = CurrentUser.Email!;

        _logger.LogInformation("Single URL Import: {Filename} from {Url}, User: {Email}, VideoId: {VideoId}",
            filename, url, userEmail, videoId);

        // Start import process in background (like Python's threading.Thread)
        _ = Task.Run(async () =>
        {
            try
            {
                _logger.LogInformation("Starting download: {Filename}", filename);
                using var httpClient = new HttpClient();
                httpClient.Timeout = TimeSpan.FromMinutes(30);
                httpClient.DefaultRequestHeaders.UserAgent.ParseAdd("Mozilla/5.0");

                using var response = await httpClient.GetAsync(downloadUrl, HttpCompletionOption.ResponseHeadersRead);
                response.EnsureSuccessStatusCode();

                var tempPath = Path.Combine(Path.GetTempPath(), $"import_{videoId}{Path.GetExtension(filename)}");
                await using (var fileStream = System.IO.File.Create(tempPath))
                {
                    await response.Content.CopyToAsync(fileStream);
                }

                _logger.LogInformation("Downloaded: {Filename}", filename);

                // Upload to S3
                await using var uploadStream = System.IO.File.OpenRead(tempPath);
                var s3Key = await _s3.UploadVideoAsync(uploadStream, videoId, filename);
                _logger.LogInformation("Uploaded to S3: {S3Key}", s3Key);

                // Create database record
                await _db.CreateVideoTaskAsync(videoId, filename, userId, userEmail, "in_queue", s3Key);
                _logger.LogInformation("Created task: {VideoId}", videoId);

                // Trigger worker (match Python import-url)
                await TriggerWorkerAfterUploadAsync(videoId, userId, filename, s3Key);

                // Notify via WebSocket (match Python)
                await _taskUpdateHub.NotifyTaskUpdateAsync(userId, new { video_id = videoId, status = "in_queue", filename });

                // Cleanup temp file
                try { System.IO.File.Delete(tempPath); } catch { /* ignore */ }

                _logger.LogInformation("Single URL import completed: {Filename}", filename);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Single URL import failed: {Filename}", filename);
                try
                {
                    await _db.CreateVideoTaskAsync(videoId, filename, userId, userEmail, "failed");
                }
                catch { /* ignore */ }
            }
        });

        return Ok(new
        {
            success = true,
            video_id = videoId,
            filename,
            message = "Video import started successfully"
        });
    }

    private static string ConvertToDirectUrl(string url)
    {
        if (url.Contains("wolkesicher.de/s/") || url.Contains("/s/"))
        {
            if (url.EndsWith("/download")) return url;
            var baseUrl = url.Contains("?") ? url.Split('?')[0] : url;
            return $"{baseUrl}/download";
        }
        if (url.Contains("nextcloud", StringComparison.OrdinalIgnoreCase) && url.Contains("/s/"))
        {
            if (!url.EndsWith("/download")) return $"{url}/download";
        }
        return url;
    }

    private static string ExtractFilenameFromUrl(string url)
    {
        try
        {
            var cleanUrl = url.Split('?')[0];
            var filename = cleanUrl.Split('/').LastOrDefault() ?? "";
            if (string.IsNullOrEmpty(filename) || !filename.Contains('.'))
            {
                foreach (var part in cleanUrl.Split('/').Reverse())
                {
                    if (part.Contains('.') && part.Length > 3)
                    {
                        filename = part;
                        break;
                    }
                }
            }
            if (string.IsNullOrEmpty(filename) || !filename.Contains('.'))
                filename = "imported_video.mp4";
            return Uri.UnescapeDataString(filename);
        }
        catch
        {
            return "imported_video.mp4";
        }
    }

    private static bool IsValidVideoFilename(string filename)
    {
        var validExtensions = new[] { ".mp4", ".avi", ".mov", ".wmv", ".mkv", ".ts", ".m4v", ".flv", ".webm" };
        return validExtensions.Any(ext => filename.EndsWith(ext, StringComparison.OrdinalIgnoreCase));
    }

    [HttpGet("list")]
    public async Task<IActionResult> List()
    {
        if (CurrentUser == null)
            return Unauthorized(new { error = "Authentication required" });

        try
        {
            var tasks = IsSuperAdmin
                ? await _db.GetAllVideoTasksAsync()
                : await _db.GetUserVideoTasksAsync(CurrentUser.Uid!);

            if (tasks == null || tasks.Count == 0)
                return Ok(new { videos = Array.Empty<object>(), total = 0, timestamp = DateTime.UtcNow.ToString("o"), message = "No videos found for this user" });

            var videos = tasks.Select(t => new
            {
                id = t.GetValueOrDefault("video_id") ?? t.GetValueOrDefault("id"),
                video_id = t.GetValueOrDefault("video_id") ?? t.GetValueOrDefault("id"),
                filename = t.GetValueOrDefault("filename"),
                video_name = t.GetValueOrDefault("filename"),
                status = t.GetValueOrDefault("status"),
                upload_date = t.GetValueOrDefault("created_at") ?? t.GetValueOrDefault("upload_date"),
                date = t.GetValueOrDefault("created_at") ?? t.GetValueOrDefault("upload_date"),
                user_email = t.GetValueOrDefault("user_email"),
                created_at = t.GetValueOrDefault("created_at"),
                updated_at = t.GetValueOrDefault("updated_at"),
                cancelled = t.GetValueOrDefault("cancelled"),
                cancelled_at = t.GetValueOrDefault("cancelled_at"),
                cancelled_by = t.GetValueOrDefault("cancelled_by"),
                cancellation_reason = t.GetValueOrDefault("cancellation_reason"),
                cancellation_requested = t.GetValueOrDefault("cancellation_requested"),
                cancellation_requested_at = t.GetValueOrDefault("cancellation_requested_at"),
                progress_percent = t.GetValueOrDefault("progress_percent") ?? 0
            }).ToList();

            return Ok(new { videos, total = videos.Count, timestamp = DateTime.UtcNow.ToString("o") });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error fetching video list");
            return Ok(new { videos = Array.Empty<object>(), total = 0, error_message = $"Database temporarily unavailable: {ex.Message}", timestamp = DateTime.UtcNow.ToString("o") });
        }
    }

    [HttpGet("status/{videoId}")]
    public async Task<IActionResult> Status(string videoId)
    {
        if (CurrentUser == null)
            return Unauthorized(new { error = "Authentication required" });

        var task = await _db.GetVideoTaskAsync(videoId);
        if (task == null)
            return NotFound(new { error = "Video not found" });

        var ownerId = task.GetValueOrDefault("user_id")?.ToString();
        if (!IsSuperAdmin && ownerId != CurrentUser.Uid)
            return StatusCode(403, new { error = "Access denied" });

        return Ok(new
        {
            video_id = task.GetValueOrDefault("video_id"),
            filename = task.GetValueOrDefault("filename"),
            status = task.GetValueOrDefault("status"),
            upload_date = task.GetValueOrDefault("created_at"),
            updated_at = task.GetValueOrDefault("updated_at"),
            user_email = task.GetValueOrDefault("user_email")
        });
    }

    [HttpGet("download/{videoId}")]
    public async Task<IActionResult> Download(string videoId)
    {
        if (CurrentUser == null)
            return Unauthorized(new { error = "Authentication required" });

        var task = await _db.GetVideoTaskAsync(videoId);
        if (task == null)
            return NotFound(new { error = "Video not found" });

        var ownerId = task.GetValueOrDefault("user_id")?.ToString();
        if (!IsSuperAdmin && ownerId != CurrentUser.Uid)
            return StatusCode(403, new { error = "Access denied" });

        var status = task.GetValueOrDefault("status")?.ToString();
        if (status != "done" && status != "completed")
            return BadRequest(new { error = "PDF not ready yet" });

        var filename = task.GetValueOrDefault("filename")?.ToString();
        var downloadUrl = _s3.GetDownloadPdfUrl(videoId, filename);
        return Ok(new { download_url = downloadUrl, video_id = videoId, filename });
    }

    [HttpPost("cancel/{videoId}")]
    public async Task<IActionResult> Cancel(string videoId, [FromBody] CancelRequest? body)
    {
        if (CurrentUser == null)
            return Unauthorized(new { error = "Authentication required" });

        var task = await _db.GetVideoTaskAsync(videoId);
        if (task == null)
            return NotFound(new { error = "Video not found" });

        var ownerId = task.GetValueOrDefault("user_id")?.ToString();
        if (!IsSuperAdmin && ownerId != CurrentUser.Uid)
            return StatusCode(403, new { error = "Access denied" });

        var currentStatus = task.GetValueOrDefault("status")?.ToString();
        var reason = body?.Reason ?? "User requested cancellation";
        var cleanupCompleted = body?.CleanupCompleted ?? false;

        var success = await _db.CancelVideoTaskAsync(videoId, CurrentUser.Email!, reason);
        if (!success)
            return StatusCode(500, new { error = "Failed to cancel video" });

        string message;
        if (currentStatus is "done" or "completed")
        {
            if (cleanupCompleted)
            {
                await TryCleanupS3ForCancelAsync(videoId, task);
                message = "Completed video cancelled and cleaned up";
            }
            else
            {
                message = "Video marked as cancelled (files preserved)";
            }
        }
        else if (currentStatus == "failed")
        {
            await TryCleanupS3ForCancelAsync(videoId, task, videoOnly: true);
            message = "Failed video cancelled";
        }
        else if (currentStatus == "processing")
        {
            message = "Processing video cancellation initiated - worker will stop shortly";
        }
        else if (currentStatus is "in_queue" or "uploaded")
        {
            await TryCleanupS3ForCancelAsync(videoId, task, videoOnly: true);
            message = "Queued video cancelled successfully";
        }
        else
        {
            message = $"Video cancelled (was in {currentStatus} state)";
        }

        var statusToSend = (currentStatus == "processing") ? "cancelling" : "cancelled";
        await _taskUpdateHub.NotifyTaskUpdateAsync(CurrentUser.Uid!, new { video_id = videoId, status = statusToSend, message = "Video cancelled by user" });

        return Ok(new
        {
            success = true,
            message,
            video_id = videoId,
            cancelled_by = CurrentUser.Email,
            reason
        });
    }

    /// <summary>
    /// Delete S3 objects when cancelling a video (match Python cleanup behavior).
    /// </summary>
    private async Task TryCleanupS3ForCancelAsync(string videoId, Dictionary<string, object?> task, bool videoOnly = false)
    {
        try
        {
            var s3Key = task.GetValueOrDefault("s3_key")?.ToString();
            if (!string.IsNullOrEmpty(s3Key))
            {
                await _s3.DeleteFileAsync(s3Key);
            }
            if (!videoOnly)
            {
                var pdfKey = $"pdfs/{videoId}/{videoId}.pdf";
                await _s3.DeleteFileAsync(pdfKey);
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Error cleaning up S3 files for cancelled video {VideoId}", videoId);
        }
    }

    [HttpPost("charge/{videoId}")]
    public async Task<IActionResult> Charge(string videoId, [FromBody] ChargeVideoRequest? request)
    {
        if (CurrentUser == null)
            return Unauthorized(new { error = "Authentication required" });

        if (request == null || request.DurationMinutes <= 0)
            return BadRequest(new { error = "DurationMinutes must be greater than zero" });

        var task = await _db.GetVideoTaskAsync(videoId);
        if (task == null)
            return NotFound(new { error = "Video not found" });

        var ownerId = task.GetValueOrDefault("user_id")?.ToString();
        if (!IsSuperAdmin && ownerId != CurrentUser.Uid)
            return StatusCode(403, new { error = "Access denied" });

        var creditsToCharge = _videoPricingService.CalculateCreditsForMinutes(request.DurationMinutes);
        if (creditsToCharge <= 0)
        {
            return Ok(new
            {
                video_id = videoId,
                duration_minutes = request.DurationMinutes,
                credits_charged = 0,
                message = "No charge applied"
            });
        }

        var holderId = UidToHolderId(CurrentUser.Uid!);

        try
        {
            // Load user wallets and find credit wallet (currency ID 1)
            var userWalletHolder = await _walletClient.WalletsAsync(holderId);
            if (userWalletHolder.WalletHolder == null || userWalletHolder.Wallets == null || !userWalletHolder.Wallets.Any())
                return NotFound(new { error = "User wallet not found" });

            var userCreditWallet = userWalletHolder.Wallets.FirstOrDefault(w => w.CurrencyID == 1);
            if (userCreditWallet == null)
                return NotFound(new { error = "User credit wallet not found" });

            var userBalance = (decimal)userCreditWallet.Amount;
            var creditAmount = (decimal)creditsToCharge;

            if (userBalance < creditAmount)
            {
                return StatusCode(402, new
                {
                    error = "Insufficient credits to charge for this video",
                    required_credits = creditAmount,
                    available_credits = userBalance
                });
            }

            // Get system wallet (destination)
            var systemWallet = await _walletClient.SystemWalletAsync();
            var systemCreditWalletId = systemWallet.Wallets?.FirstOrDefault(w => w.Type == "__SYSTEM__")?.WalletId;
            if (systemCreditWalletId == null)
                return StatusCode(500, new { error = "System wallet not found" });

            var transaction = new TransactionRequest
            {
                ServiceName = "ThakiiVideoService",
                Tag = $"VideoCharge-{videoId}",
                Notes = request.Notes ?? $"Charge for video {videoId}, duration {request.DurationMinutes} minutes",
                Transactions = new List<TransactionDetailsRequest>
                {
                    new TransactionDetailsRequest
                    {
                        SourceWalletId = userCreditWallet.WalletId,
                        DestinationWalletId = (Guid)systemCreditWalletId,
                        Amount = (double)creditAmount
                    }
                }
            };

            // Initiate and execute transaction
            var txResult = await _walletClient.InitiateAsync(transaction);
            await _walletClient.ExecuteAsync(txResult.TransactionHeader.TxId);

            _logger.LogInformation("Charged user {UserId} {Credits} credits for video {VideoId}. TxId={TxId}",
                CurrentUser.Uid, creditsToCharge, videoId, txResult.TransactionHeader.TxId);

            return Ok(new
            {
                video_id = videoId,
                duration_minutes = request.DurationMinutes,
                credits_charged = creditsToCharge,
                transaction_id = txResult.TransactionHeader.TxId,
                message = "Video charge completed successfully"
            });
        }
        catch (ApiException ex)
        {
            _logger.LogError(ex, "Wallet API error while charging video {VideoId} for user {UserId}", videoId, CurrentUser.Uid);
            return StatusCode(ex.StatusCode, new { error = "Wallet API error while charging for video", details = ex.Message });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Unexpected error while charging video {VideoId} for user {UserId}", videoId, CurrentUser.Uid);
            return StatusCode(500, new { error = "Unexpected error while charging for video", details = ex.Message });
        }
    }

    [HttpGet("assets")]
    public async Task<IActionResult> GetAssets()
    {
        var items = await _videoCatalogService.GetAllPricingAssetsAsync();

        var assets = items.Select(i => new
        {
            id = i.Guid,
            name = i.Name,
            description = i.Description,
            type = i.Type,
            minutes_per_credit = i.AdditionalParams != null && i.AdditionalParams.TryGetValue("minutes_per_credit", out var mpc) ? mpc : null,
            credits_per_unit = i.AdditionalParams != null && i.AdditionalParams.TryGetValue("credits_per_unit", out var cpu) ? cpu : null,
            additional_params = i.AdditionalParams
        }).ToList();

        return Ok(new
        {
            assets,
            total = assets.Count,
            timestamp = DateTime.UtcNow.ToString("o")
        });
    }
}

public class CancelRequest
{
    public string? Reason { get; set; }
    public bool? CleanupCompleted { get; set; }
}

public class ChargeVideoRequest
{
    public double DurationMinutes { get; set; }
    public string? Notes { get; set; }
}

public class AssembleFileRequest
{
    public string? FileId { get; set; }
    public int TotalChunks { get; set; }
    public string? OriginalFilename { get; set; }
}

public class ImportUrlRequest
{
    public string? Url { get; set; }
    public string? Filename { get; set; }
}
