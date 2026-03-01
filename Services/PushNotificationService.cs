namespace ThakiiBackend.Api.Services;

public interface IPushNotificationService
{
    Dictionary<string, object?> SendTestNotification(string testType = "simple");
}

public class PushNotificationService : IPushNotificationService
{
    private readonly ILogger<PushNotificationService> _logger;

    public PushNotificationService(ILogger<PushNotificationService> logger)
    {
        _logger = logger;
    }

    public Dictionary<string, object?> SendTestNotification(string testType = "simple")
    {
        _logger.LogInformation("Sending test notification of type {TestType}", testType);

        // Stub implementation - Firebase push notifications would go here
        return new Dictionary<string, object?>
        {
            ["success"] = true,
            ["message"] = "Test notification sent (stub)",
            ["type"] = testType,
            ["timestamp"] = DateTime.UtcNow.ToString("o")
        };
    }
}
