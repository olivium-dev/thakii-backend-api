using System.Collections.Concurrent;

namespace ThakiiBackend.Api.Services;

public interface IAdminManagerService
{
    List<Dictionary<string, object?>> GetAllAdmins();
    Dictionary<string, object?> AddAdmin(string email, string role, string addedBy, string description = "");
    Dictionary<string, object?> UpdateAdmin(string adminId, Dictionary<string, object?> updates, string updatedBy);
    Dictionary<string, object?> RemoveAdmin(string adminId, string removedBy);
    Dictionary<string, object?> GetAdminStats();
    void EnsureSuperAdminsExist();
}

public class AdminManagerService : IAdminManagerService
{
    private readonly ConcurrentDictionary<string, Dictionary<string, object?>> _admins = new();
    private readonly string[] _superAdmins;
    private readonly ILogger<AdminManagerService> _logger;

    public AdminManagerService(IConfiguration config, ILogger<AdminManagerService> logger)
    {
        _logger = logger;
        _superAdmins = config.GetSection("SuperAdmins").Get<string[]>() ?? new[] { "ouday.khaled@gmail.com", "appsaawt@gmail.com" };
        EnsureSuperAdminsExist();
    }

    public void EnsureSuperAdminsExist()
    {
        foreach (var email in _superAdmins)
        {
            var existing = _admins.Values.FirstOrDefault(a => a.GetValueOrDefault("email")?.ToString() == email);
            if (existing == null)
            {
                var id = Guid.NewGuid().ToString();
                _admins[id] = new Dictionary<string, object?>
                {
                    ["id"] = id,
                    ["email"] = email,
                    ["role"] = "super_admin",
                    ["added_by"] = "system",
                    ["description"] = "Super admin (from config)",
                    ["created_at"] = DateTime.UtcNow.ToString("o"),
                    ["active"] = true
                };
            }
        }
    }

    public List<Dictionary<string, object?>> GetAllAdmins()
    {
        return _admins.Values.Where(a => a.GetValueOrDefault("active") is true).ToList();
    }

    public Dictionary<string, object?> AddAdmin(string email, string role, string addedBy, string description = "")
    {
        var existing = _admins.Values.FirstOrDefault(a => a.GetValueOrDefault("email")?.ToString() == email);
        if (existing != null)
            return new Dictionary<string, object?> { ["success"] = false, ["error"] = $"Admin with email {email} already exists" };

        var id = Guid.NewGuid().ToString();
        var admin = new Dictionary<string, object?>
        {
            ["id"] = id,
            ["email"] = email,
            ["role"] = role,
            ["added_by"] = addedBy,
            ["description"] = description,
            ["created_at"] = DateTime.UtcNow.ToString("o"),
            ["active"] = true
        };
        _admins[id] = admin;
        _logger.LogInformation("Added admin {Email} with role {Role} by {AddedBy}", email, role, addedBy);
        return new Dictionary<string, object?> { ["success"] = true, ["admin"] = admin };
    }

    public Dictionary<string, object?> UpdateAdmin(string adminId, Dictionary<string, object?> updates, string updatedBy)
    {
        if (!_admins.TryGetValue(adminId, out var admin))
            return new Dictionary<string, object?> { ["success"] = false, ["error"] = "Admin not found" };

        foreach (var kv in updates)
        {
            if (kv.Key != "id" && kv.Key != "created_at")
                admin[kv.Key] = kv.Value;
        }
        admin["updated_at"] = DateTime.UtcNow.ToString("o");
        admin["updated_by"] = updatedBy;
        _logger.LogInformation("Updated admin {AdminId} by {UpdatedBy}", adminId, updatedBy);
        return new Dictionary<string, object?> { ["success"] = true, ["admin"] = admin };
    }

    public Dictionary<string, object?> RemoveAdmin(string adminId, string removedBy)
    {
        if (!_admins.TryGetValue(adminId, out var admin))
            return new Dictionary<string, object?> { ["success"] = false, ["error"] = "Admin not found" };

        // Don't allow removing super admins
        var email = admin.GetValueOrDefault("email")?.ToString();
        if (email != null && _superAdmins.Contains(email))
            return new Dictionary<string, object?> { ["success"] = false, ["error"] = "Cannot remove super admin" };

        admin["active"] = false;
        admin["removed_by"] = removedBy;
        admin["removed_at"] = DateTime.UtcNow.ToString("o");
        _logger.LogInformation("Removed admin {AdminId} by {RemovedBy}", adminId, removedBy);
        return new Dictionary<string, object?> { ["success"] = true, ["message"] = $"Admin {adminId} removed" };
    }

    public Dictionary<string, object?> GetAdminStats()
    {
        var activeAdmins = _admins.Values.Where(a => a.GetValueOrDefault("active") is true).ToList();
        return new Dictionary<string, object?>
        {
            ["total_admins"] = activeAdmins.Count,
            ["super_admins"] = activeAdmins.Count(a => a.GetValueOrDefault("role")?.ToString() == "super_admin"),
            ["regular_admins"] = activeAdmins.Count(a => a.GetValueOrDefault("role")?.ToString() == "admin"),
            ["timestamp"] = DateTime.UtcNow.ToString("o")
        };
    }
}
