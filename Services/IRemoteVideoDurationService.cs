namespace ThakiiBackend.Api.Services;

/// <summary>
/// Estimates video duration from a remote URL without full download.
/// Uses Range request + ffprobe when possible, with fallbacks for unsupported servers.
/// </summary>
public interface IRemoteVideoDurationService
{
    /// <summary>
    /// Gets estimated duration in minutes for a remote video.
    /// Tries: (1) Range + ffprobe, (2) size-based estimate from Content-Length, (3) conservative minimum.
    /// </summary>
    /// <param name="url">Direct URL to the video file.</param>
    /// <param name="filename">Filename (for temp file extension).</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>Estimated duration in minutes and the source of the estimate.</returns>
    Task<(double DurationMinutes, string Source)> GetEstimatedDurationAsync(
        string url,
        string filename,
        CancellationToken cancellationToken = default);
}
