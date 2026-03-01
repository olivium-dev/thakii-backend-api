namespace ThakiiBackend.Api.Services;

/// <summary>
/// Sends task updates to connected clients via SignalR (matches Python websocket_manager.notify_task_update).
/// </summary>
public interface ITaskUpdateHubService
{
    Task NotifyTaskUpdateAsync(string userId, object taskData, CancellationToken cancellationToken = default);
}
