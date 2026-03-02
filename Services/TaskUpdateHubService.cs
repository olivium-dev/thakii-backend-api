using Microsoft.AspNetCore.SignalR;
using ThakiiBackend.Api.Hubs;
using ThakiiBackend.Api.Middleware.SocketIo;

namespace ThakiiBackend.Api.Services;

public class TaskUpdateHubService : ITaskUpdateHubService
{
    private readonly IHubContext<TaskUpdateHub> _hubContext;
    private readonly SocketIoServer _socketIoServer;
    private readonly ILogger<TaskUpdateHubService> _logger;

    public TaskUpdateHubService(
        IHubContext<TaskUpdateHub> hubContext,
        SocketIoServer socketIoServer,
        ILogger<TaskUpdateHubService> logger)
    {
        _hubContext = hubContext;
        _socketIoServer = socketIoServer;
        _logger = logger;
    }

    public async Task NotifyTaskUpdateAsync(string userId, object taskData, CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrEmpty(userId)) return;
        var room = $"user_{userId}";
        try
        {
            await _hubContext.Clients.Group(room).SendAsync(TaskUpdateHub.TaskUpdateEvent, taskData, cancellationToken);
            _socketIoServer.EmitToRoom(room, "task_update", taskData);
            _logger.LogDebug("Task update sent to room {Room}", room);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to send task update to room {Room}", room);
        }
    }
}
