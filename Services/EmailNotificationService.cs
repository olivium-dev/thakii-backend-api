using System.Collections.Concurrent;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace ThakiiBackend.Api.Services;

public interface IEmailNotificationService
{
    bool IsConfigured { get; }
    string ApiUrl { get; }
    string FromEmail { get; }
    string FromName { get; }
    string? ApiKeyPreview { get; }
    List<string> AdditionalRecipients { get; set; }
    bool SendTestEmail(string recipient);
    bool SendProcessingCompleteNotification(string userEmail, string videoId, string filename, string status, string? errorMessage = null, string? pdfDownloadUrl = null);
    List<string> GetAdditionalRecipientsFromDb();
    bool UpdateAdditionalRecipientsInDb(List<string> emails);
}

public class EmailNotificationService : IEmailNotificationService
{
    private readonly string? _apiKey;
    private readonly ILogger<EmailNotificationService> _logger;
    private readonly IHttpClientFactory _httpClientFactory;
    private readonly ConcurrentBag<string> _recipients = new();

    public bool IsConfigured => !string.IsNullOrEmpty(_apiKey);
    public string ApiUrl => "https://api.brevo.com/v3/smtp/email";
    public string FromEmail { get; }
    public string FromName { get; }
    public string? ApiKeyPreview => !string.IsNullOrEmpty(_apiKey) ? $"{_apiKey[..Math.Min(20, _apiKey.Length)]}..." : null;
    public List<string> AdditionalRecipients { get; set; } = new();

    public EmailNotificationService(IConfiguration config, ILogger<EmailNotificationService> logger, IHttpClientFactory httpClientFactory)
    {
        _logger = logger;
        _httpClientFactory = httpClientFactory;
        _apiKey = Environment.GetEnvironmentVariable("BREVO_API_KEY") ?? config["Email:BrevoApiKey"];
        FromEmail = config["Email:FromEmail"] ?? "noreply@thakii.com";
        FromName = config["Email:FromName"] ?? "Thakii";

        var recipientsConfig = config.GetSection("Email:AdditionalRecipients").Get<string[]>();
        if (recipientsConfig != null)
        {
            AdditionalRecipients = recipientsConfig.ToList();
            foreach (var r in recipientsConfig) _recipients.Add(r);
        }
    }

    public bool SendTestEmail(string recipient)
    {
        if (!IsConfigured)
        {
            _logger.LogWarning("Email service not configured (no API key)");
            return false;
        }

        try
        {
            var payload = new
            {
                sender = new { email = FromEmail, name = FromName },
                to = new[] { new { email = recipient, name = recipient } },
                subject = "Thakii - Test Email",
                htmlContent = "<h1>Test Email</h1><p>This is a test email from Thakii backend service.</p>"
            };

            return SendBrevoEmail(payload);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to send test email to {Recipient}", recipient);
            return false;
        }
    }

    public bool SendProcessingCompleteNotification(string userEmail, string videoId, string filename, string status,
        string? errorMessage = null, string? pdfDownloadUrl = null)
    {
        if (!IsConfigured) return false;

        try
        {
            var subject = status == "completed"
                ? $"Thakii - Video '{filename}' processing completed"
                : $"Thakii - Video '{filename}' processing failed";

            var htmlContent = status == "completed"
                ? $"<h2>Processing Complete</h2><p>Your video <strong>{filename}</strong> has been processed successfully.</p>"
                : $"<h2>Processing Failed</h2><p>Your video <strong>{filename}</strong> failed to process.</p><p>Error: {errorMessage}</p>";

            var recipients = new List<object> { new { email = userEmail, name = userEmail } };
            foreach (var r in AdditionalRecipients)
                recipients.Add(new { email = r, name = r });

            var payload = new
            {
                sender = new { email = FromEmail, name = FromName },
                to = recipients,
                subject,
                htmlContent
            };

            return SendBrevoEmail(payload);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to send processing notification for video {VideoId}", videoId);
            return false;
        }
    }

    private bool SendBrevoEmail(object payload)
    {
        try
        {
            using var client = _httpClientFactory.CreateClient();
            client.DefaultRequestHeaders.Add("api-key", _apiKey);
            var json = JsonSerializer.Serialize(payload);
            var content = new StringContent(json, Encoding.UTF8, "application/json");
            var response = client.PostAsync(ApiUrl, content).Result;
            return response.IsSuccessStatusCode;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Brevo API call failed");
            return false;
        }
    }

    public List<string> GetAdditionalRecipientsFromDb()
    {
        return _recipients.ToList();
    }

    public bool UpdateAdditionalRecipientsInDb(List<string> emails)
    {
        // Clear and re-add
        while (_recipients.TryTake(out _)) { }
        foreach (var email in emails) _recipients.Add(email);
        AdditionalRecipients = emails;
        return true;
    }
}
