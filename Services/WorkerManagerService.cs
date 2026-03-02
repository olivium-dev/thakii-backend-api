namespace ThakiiBackend.Api.Services;

public interface IWorkerManagerService
{
    Dictionary<string, object?> GetAllWorkersHealth();
    Dictionary<string, object?> TriggerWithFallback(Dictionary<string, object?> payload);
}

public class WorkerManagerService : IWorkerManagerService
{
    private readonly ILogger<WorkerManagerService> _logger;
    private readonly IHttpClientFactory _httpClientFactory;
    private readonly string _primaryWorkerUrl;

    public WorkerManagerService(IConfiguration config, ILogger<WorkerManagerService> logger, IHttpClientFactory httpClientFactory)
    {
        _logger = logger;
        _httpClientFactory = httpClientFactory;
        // Env override for local dev when primary worker host (e.g. thakii-03) is not resolvable
        _primaryWorkerUrl = Environment.GetEnvironmentVariable("WORKER_SERVICE_URL")
            ?? config["Worker:ServiceUrl"]
            ?? "https://thakii-02.fanusdigital.site/thakii-worker";
    }

    public Dictionary<string, object?> GetAllWorkersHealth()
    {
        var workers = new List<Dictionary<string, object?>>();
        var healthyCount = 0;

        // Check primary worker
        var isHealthy = CheckWorkerHealth(_primaryWorkerUrl);
        if (isHealthy) healthyCount++;

        workers.Add(new Dictionary<string, object?>
        {
            ["worker_id"] = "primary",
            ["url"] = _primaryWorkerUrl,
            ["status"] = isHealthy ? "healthy" : "unhealthy",
            ["last_check"] = DateTime.UtcNow.ToString("o")
        });

        return new Dictionary<string, object?>
        {
            ["workers"] = workers,
            ["summary"] = new Dictionary<string, object?>
            {
                ["healthy_workers"] = healthyCount,
                ["total_workers"] = workers.Count
            },
            ["priority_mode"] = "primary",
            ["timestamp"] = DateTime.UtcNow.ToString("o")
        };
    }

    public Dictionary<string, object?> TriggerWithFallback(Dictionary<string, object?> payload)
    {
        try
        {
            using var client = _httpClientFactory.CreateClient();
            client.Timeout = TimeSpan.FromSeconds(10);
            var json = System.Text.Json.JsonSerializer.Serialize(payload);
            var content = new System.Net.Http.StringContent(json, System.Text.Encoding.UTF8, "application/json");
            // Worker API expects /process-from-s3 (same as Python backend)
            var response = client.PostAsync($"{_primaryWorkerUrl.TrimEnd('/')}/process-from-s3", content).Result;

            return new Dictionary<string, object?>
            {
                ["success"] = response.IsSuccessStatusCode,
                ["worker_used"] = "primary",
                ["worker_url"] = _primaryWorkerUrl,
                ["error"] = response.IsSuccessStatusCode ? null : $"HTTP {response.StatusCode}"
            };
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Worker trigger failed for primary worker");
            return new Dictionary<string, object?>
            {
                ["success"] = false,
                ["worker_used"] = "primary",
                ["worker_url"] = _primaryWorkerUrl,
                ["error"] = ex.Message
            };
        }
    }

    private bool CheckWorkerHealth(string url)
    {
        try
        {
            using var client = _httpClientFactory.CreateClient();
            client.Timeout = TimeSpan.FromSeconds(5);
            var response = client.GetAsync($"{url.TrimEnd('/')}/health").Result;
            return response.IsSuccessStatusCode;
        }
        catch
        {
            return false;
        }
    }
}
