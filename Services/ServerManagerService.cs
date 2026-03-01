using System.Collections.Concurrent;

namespace ThakiiBackend.Api.Services;

public interface IServerManagerService
{
    List<Dictionary<string, object?>> GetAllServers();
    Dictionary<string, object?> AddServer(string name, string url, string type = "processing", string description = "");
    Dictionary<string, object?> UpdateServer(string serverId, Dictionary<string, object?> updates);
    Dictionary<string, object?> RemoveServer(string serverId);
    Dictionary<string, object?> CheckAllServersHealth();
}

public class ServerManagerService : IServerManagerService
{
    private readonly ConcurrentDictionary<string, Dictionary<string, object?>> _servers = new();
    private readonly ILogger<ServerManagerService> _logger;
    private readonly IHttpClientFactory _httpClientFactory;

    public ServerManagerService(IConfiguration config, ILogger<ServerManagerService> logger, IHttpClientFactory httpClientFactory)
    {
        _logger = logger;
        _httpClientFactory = httpClientFactory;

        // Load default worker URL from config
        var workerUrl = config["Worker:ServiceUrl"];
        if (!string.IsNullOrEmpty(workerUrl))
        {
            var id = Guid.NewGuid().ToString();
            _servers[id] = new Dictionary<string, object?>
            {
                ["id"] = id,
                ["name"] = "primary-worker",
                ["url"] = workerUrl,
                ["type"] = "processing",
                ["description"] = "Primary worker from config",
                ["status"] = "unknown",
                ["last_health_check"] = null,
                ["created_at"] = DateTime.UtcNow.ToString("o"),
                ["active"] = true
            };
        }
    }

    public List<Dictionary<string, object?>> GetAllServers()
    {
        return _servers.Values.ToList();
    }

    public Dictionary<string, object?> AddServer(string name, string url, string type = "processing", string description = "")
    {
        var id = Guid.NewGuid().ToString();
        var server = new Dictionary<string, object?>
        {
            ["id"] = id,
            ["name"] = name,
            ["url"] = url,
            ["type"] = type,
            ["description"] = description,
            ["status"] = "unknown",
            ["last_health_check"] = null,
            ["created_at"] = DateTime.UtcNow.ToString("o"),
            ["active"] = true
        };
        _servers[id] = server;
        _logger.LogInformation("Added server {Name} at {Url} with id {Id}", name, url, id);
        return new Dictionary<string, object?> { ["success"] = true, ["server"] = server };
    }

    public Dictionary<string, object?> UpdateServer(string serverId, Dictionary<string, object?> updates)
    {
        if (!_servers.TryGetValue(serverId, out var server))
            return new Dictionary<string, object?> { ["success"] = false, ["error"] = "Server not found" };

        foreach (var kv in updates)
        {
            if (kv.Key != "id" && kv.Key != "created_at")
                server[kv.Key] = kv.Value;
        }
        server["updated_at"] = DateTime.UtcNow.ToString("o");
        _logger.LogInformation("Updated server {ServerId}", serverId);
        return new Dictionary<string, object?> { ["success"] = true, ["server"] = server };
    }

    public Dictionary<string, object?> RemoveServer(string serverId)
    {
        if (_servers.TryRemove(serverId, out _))
        {
            _logger.LogInformation("Removed server {ServerId}", serverId);
            return new Dictionary<string, object?> { ["success"] = true, ["message"] = $"Server {serverId} removed" };
        }
        return new Dictionary<string, object?> { ["success"] = false, ["error"] = "Server not found" };
    }

    public Dictionary<string, object?> CheckAllServersHealth()
    {
        var workers = new List<Dictionary<string, object?>>();
        var healthyCount = 0;

        foreach (var kv in _servers)
        {
            var server = kv.Value;
            var url = server.GetValueOrDefault("url")?.ToString();
            var isHealthy = false;

            if (!string.IsNullOrEmpty(url))
            {
                try
                {
                    using var client = _httpClientFactory.CreateClient();
                    client.Timeout = TimeSpan.FromSeconds(5);
                    var response = client.GetAsync($"{url.TrimEnd('/')}/health").Result;
                    isHealthy = response.IsSuccessStatusCode;
                }
                catch (Exception ex)
                {
                    _logger.LogWarning(ex, "Health check failed for server {Url}", url);
                }
            }

            if (isHealthy) healthyCount++;

            server["status"] = isHealthy ? "healthy" : "unhealthy";
            server["last_health_check"] = DateTime.UtcNow.ToString("o");

            workers.Add(new Dictionary<string, object?>(server));
        }

        return new Dictionary<string, object?>
        {
            ["workers"] = workers,
            ["summary"] = new Dictionary<string, object?>
            {
                ["healthy_workers"] = healthyCount,
                ["total_workers"] = _servers.Count
            },
            ["priority_mode"] = "primary",
            ["timestamp"] = DateTime.UtcNow.ToString("o")
        };
    }
}
