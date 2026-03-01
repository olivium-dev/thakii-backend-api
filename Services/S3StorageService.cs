using System.IO;
using Amazon;
using Amazon.S3;
using Amazon.S3.Model;

namespace ThakiiBackend.Api.Services;

public interface IS3StorageService
{
    Task<string> UploadVideoAsync(Stream fileStream, string videoId, string filename);
    string GetDownloadPdfUrl(string videoId, string? originalFilename = null);
    Task DeleteFileAsync(string key);
}

public class S3StorageService : IS3StorageService
{
    private readonly IAmazonS3 _s3Client;
    private readonly string _bucketName;
    private readonly ILogger<S3StorageService> _logger;

    public S3StorageService(IConfiguration config, ILogger<S3StorageService> logger)
    {
        _logger = logger;

        var region = config["AWS:Region"] ?? Environment.GetEnvironmentVariable("AWS_DEFAULT_REGION") ?? "us-east-2";
        _bucketName = config["AWS:S3Bucket"] ?? Environment.GetEnvironmentVariable("S3_BUCKET_NAME") ?? "thakii-video-storage-1753883631";

        // Use default credential chain: env vars (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY), profile, or instance role
        var regionEndpoint = RegionEndpoint.GetBySystemName(region);
        _s3Client = new AmazonS3Client(regionEndpoint);

        _logger.LogInformation("Using AWS S3 storage. Bucket={Bucket}, Region={Region}", _bucketName, region);
    }

    public async Task<string> UploadVideoAsync(Stream fileStream, string videoId, string filename)
    {
        var safeFileName = Path.GetFileName(filename) ?? filename;
        var videoKey = $"videos/{videoId}/{safeFileName}";

        var request = new PutObjectRequest
        {
            BucketName = _bucketName,
            Key = videoKey,
            InputStream = fileStream,
            ContentType = "video/mp4"
        };

        await _s3Client.PutObjectAsync(request);
        _logger.LogInformation("Uploaded video {VideoId} to S3: {Key}", videoId, videoKey);
        return videoKey;
    }

    public string GetDownloadPdfUrl(string videoId, string? originalFilename = null)
    {
        // Match Python: pdfs/{video_id}/{video_id}.pdf
        var pdfKey = $"pdfs/{videoId}/{videoId}.pdf";

        var pdfDownloadFilename = !string.IsNullOrEmpty(originalFilename)
            ? Path.GetFileNameWithoutExtension(originalFilename) + ".pdf"
            : $"{videoId}.pdf";

        // RFC 5987: attachment; filename*=UTF-8''percent-encoded-filename
        var encodedFilename = Uri.EscapeDataString(pdfDownloadFilename);
        var contentDisposition = $"attachment; filename*=UTF-8''{encodedFilename}";

        var request = new GetPreSignedUrlRequest
        {
            BucketName = _bucketName,
            Key = pdfKey,
            Expires = DateTime.UtcNow.AddHours(1)
        };
        request.ResponseHeaderOverrides.ContentDisposition = contentDisposition;

        var url = _s3Client.GetPreSignedURL(request);
        _logger.LogInformation("Generated presigned PDF URL for video {VideoId}, filename {Filename}", videoId, pdfDownloadFilename);
        return url;
    }

    public async Task DeleteFileAsync(string key)
    {
        if (string.IsNullOrWhiteSpace(key)) return;
        try
        {
            await _s3Client.DeleteObjectAsync(new DeleteObjectRequest { BucketName = _bucketName, Key = key });
            _logger.LogInformation("Deleted S3 object: {Key}", key);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to delete S3 object {Key}", key);
            throw;
        }
    }
}
