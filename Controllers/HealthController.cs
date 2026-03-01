using Microsoft.AspNetCore.Mvc;

namespace ThakiiBackend.Api.Controllers;

[ApiController]
[Route("health")]
public class HealthController : ControllerBase
{
    [HttpGet]
    public IActionResult Get()
    {
        return Ok(new
        {
            service = "Thakii Lecture2PDF Service",
            status = "healthy",
            database = "PostgreSQL",
            storage = "S3",
            websocket = "enabled",
            timestamp = DateTime.UtcNow.ToString("o")
        });
    }
}
