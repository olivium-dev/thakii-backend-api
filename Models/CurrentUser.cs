namespace ThakiiBackend.Api.Models;

public class CurrentUser
{
    public string? Uid { get; set; }
    public string? Email { get; set; }
    public string? Name { get; set; }
    public string? Picture { get; set; }
    public bool EmailVerified { get; set; }
    public bool IsAdmin { get; set; }
}
