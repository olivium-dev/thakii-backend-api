using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.SignalR;

namespace ThakiiBackend.Api.Hubs;

/// <summary>
/// SignalR hub for real-time task updates. Clients join room by user_id (room name: "user_{userId}").
/// Matches Python websocket_manager: notify_task_update(user_id, task_data).
/// </summary>
[AllowAnonymous]
public class TaskUpdateHub : Hub
{
    public const string TaskUpdateEvent = "task_update";

    /// <summary>
    /// Client sends { "user_id": "..." } to join their user room.
    /// </summary>
    public async Task Join(string user_id)
    {
        if (string.IsNullOrEmpty(user_id))
        {
            await Clients.Caller.SendAsync("error", new { message = "user_id required to join room" });
            return;
        }
        var room = $"user_{user_id}";
        await Groups.AddToGroupAsync(Context.ConnectionId, room);
        await Clients.Caller.SendAsync("joined", new { room, message = $"Joined room {room}" });
    }

    public async Task Leave(string user_id)
    {
        if (!string.IsNullOrEmpty(user_id))
        {
            var room = $"user_{user_id}";
            await Groups.RemoveFromGroupAsync(Context.ConnectionId, room);
            await Clients.Caller.SendAsync("left", new { room, message = $"Left room {room}" });
        }
    }
}
