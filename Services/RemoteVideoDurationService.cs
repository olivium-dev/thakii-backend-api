using System.Diagnostics;
using System.Globalization;

namespace ThakiiBackend.Api.Services;

/// <summary>
/// Estimates video duration from a remote URL without full download.
/// Uses Range request + ffprobe when possible, with fallbacks for unsupported servers.
/// </summary>
public class RemoteVideoDurationService : IRemoteVideoDurationService
{
    private const int RangeBytes = 3 * 1024 * 1024; // 3 MB - enough for most video headers
    private const double SizeToMinutesFactor = 0.1;  // 1 MB ≈ 0.1 min (~2 Mbps conservative)
    private readonly IHttpClientFactory _httpClientFactory;
    private readonly IVideoPricingService _videoPricingService;
    private readonly ILogger<RemoteVideoDurationService> _logger;

    public RemoteVideoDurationService(
        IHttpClientFactory httpClientFactory,
        IVideoPricingService videoPricingService,
        ILogger<RemoteVideoDurationService> logger)
    {
        _httpClientFactory = httpClientFactory;
        _videoPricingService = videoPricingService;
        _logger = logger;
    }

    public async Task<(double DurationMinutes, string Source)> GetEstimatedDurationAsync(
        string url,
        string filename,
        CancellationToken cancellationToken = default)
    {
        using var httpClient = _httpClientFactory.CreateClient();
        httpClient.Timeout = TimeSpan.FromSeconds(30);
        httpClient.DefaultRequestHeaders.UserAgent.ParseAdd("Mozilla/5.0 (compatible; Thakii/1.0)");

        // Step 0: Try ffprobe directly on the URL (most accurate, may read more data).
        var durationFromUrl = GetVideoDurationMinutesFromUrl(url);
        if (durationFromUrl > 0)
        {
            _logger.LogInformation("Remote duration from ffprobe URL: {Duration:F1} min for {Url}", durationFromUrl, url);
            return (durationFromUrl, "ffprobe_url");
        }

        // Step 1: Try Range request + ffprobe
        var (durationFromProbe, gotFromProbe) = await TryGetDurationViaRangeAndFfprobeAsync(httpClient, url, filename, cancellationToken);
        if (gotFromProbe && durationFromProbe > 0)
        {
            _logger.LogInformation("Remote duration from ffprobe: {Duration:F1} min for {Url}", durationFromProbe, url);
            return (durationFromProbe, "ffprobe");
        }

        // Step 2: Fallback - size-based estimate from Content-Length
        var (durationFromSize, gotFromSize) = await TryGetDurationFromContentLengthAsync(httpClient, url, cancellationToken);
        if (gotFromSize && durationFromSize > 0)
        {
            _logger.LogInformation("Remote duration from size estimate: {Duration:F1} min for {Url}", durationFromSize, url);
            return (durationFromSize, "size_estimate");
        }

        // Step 3: Conservative fallback - require minimum credits (e.g. 5 credits worth)
        var minutesPerCredit = _videoPricingService.GetMinutesPerCredit();
        var conservativeMinutes = minutesPerCredit * 5; // 50 min at 10 min/credit = 5 credits
        _logger.LogWarning("Could not estimate duration for {Url}. Using conservative {Minutes} min ({Credits} credits).",
            url, conservativeMinutes, 5);
        return (conservativeMinutes, "conservative");
    }

    private async Task<(double DurationMinutes, bool Success)> TryGetDurationViaRangeAndFfprobeAsync(
        HttpClient httpClient,
        string url,
        string filename,
        CancellationToken cancellationToken)
    {
        string? tempPath = null;
        try
        {
            using var request = new HttpRequestMessage(HttpMethod.Get, url);
            request.Headers.Range = new System.Net.Http.Headers.RangeHeaderValue(0, RangeBytes - 1);

            using var response = await httpClient.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken);

            // 206 Partial Content = server supports Range
            if (response.StatusCode != System.Net.HttpStatusCode.PartialContent)
            {
                _logger.LogDebug("Server did not return 206 Partial Content for {Url}. Status: {Status}", url, response.StatusCode);
                return (0, false);
            }

            var content = await response.Content.ReadAsByteArrayAsync(cancellationToken);
            if (content.Length == 0)
            {
                _logger.LogDebug("Empty response for Range request to {Url}", url);
                return (0, false);
            }

            var ext = Path.GetExtension(filename);
            if (string.IsNullOrEmpty(ext)) ext = ".mp4";
            tempPath = Path.Combine(Path.GetTempPath(), $"probe_{Guid.NewGuid():N}{ext}");
            await System.IO.File.WriteAllBytesAsync(tempPath, content, cancellationToken);

            var duration = GetVideoDurationMinutes(tempPath);
            return (duration, duration > 0);
        }
        catch (Exception ex)
        {
            _logger.LogDebug(ex, "Range+ffprobe failed for {Url}", url);
            return (0, false);
        }
        finally
        {
            if (tempPath != null)
            {
                try { if (System.IO.File.Exists(tempPath)) System.IO.File.Delete(tempPath); }
                catch { /* best-effort */ }
            }
        }
    }

    private async Task<(double DurationMinutes, bool Success)> TryGetDurationFromContentLengthAsync(
        HttpClient httpClient,
        string url,
        CancellationToken cancellationToken)
    {
        try
        {
            using var request = new HttpRequestMessage(HttpMethod.Head, url);
            using var response = await httpClient.SendAsync(request, cancellationToken);
            response.EnsureSuccessStatusCode();

            var contentLength = response.Content.Headers.ContentLength;
            if (contentLength == null || contentLength <= 0)
            {
                _logger.LogDebug("No Content-Length for HEAD {Url}", url);
                return (0, false);
            }

            var sizeMb = contentLength.Value / (1024.0 * 1024.0);
            var estimatedMinutes = sizeMb * SizeToMinutesFactor; // 1 MB ≈ 0.1 min
            return (estimatedMinutes, true);
        }
        catch (Exception ex)
        {
            _logger.LogDebug(ex, "HEAD request failed for {Url}", url);
            return (0, false);
        }
    }

    private static double GetVideoDurationMinutesFromUrl(string url)
    {
        var startInfo = new ProcessStartInfo
        {
            FileName = "ffprobe",
            Arguments = $"-v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 \"{url}\"",
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true
        };

        try
        {
            using var process = Process.Start(startInfo);
            if (process == null) return 0;

            var output = process.StandardOutput.ReadToEnd();
            process.WaitForExit(10000);

            if (process.ExitCode != 0) return 0;

            if (double.TryParse(output.Trim(), NumberStyles.Any, CultureInfo.InvariantCulture, out var seconds))
                return seconds / 60.0;

            return 0;
        }
        catch
        {
            return 0;
        }
    }

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
            if (process == null) return 0;

            var output = process.StandardOutput.ReadToEnd();
            process.WaitForExit(10000);

            if (process.ExitCode != 0) return 0;

            if (double.TryParse(output.Trim(), NumberStyles.Any, CultureInfo.InvariantCulture, out var seconds))
                return seconds / 60.0;

            return 0;
        }
        catch
        {
            return 0;
        }
    }
}
