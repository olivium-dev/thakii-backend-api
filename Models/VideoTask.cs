namespace ThakiiBackend.Api.Models;

public class VideoTask
{
    public string? Id { get; set; }
    public string? VideoId { get; set; }
    public string? Filename { get; set; }
    public string? UserId { get; set; }
    public string? UserEmail { get; set; }
    public string? Status { get; set; }
    public DateTime? UploadDate { get; set; }
    public DateTime? CreatedAt { get; set; }
    public DateTime? UpdatedAt { get; set; }
    public string? S3Key { get; set; }
    public string? PdfUrl { get; set; }
    public string? ErrorMessage { get; set; }
    public bool Cancelled { get; set; }
    public DateTime? CancelledAt { get; set; }
    public string? CancelledBy { get; set; }
    public string? CancellationReason { get; set; }
    public bool CancellationRequested { get; set; }
    public DateTime? CancellationRequestedAt { get; set; }
    public int ProgressPercent { get; set; }
}
