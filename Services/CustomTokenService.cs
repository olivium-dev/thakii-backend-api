using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using System.Security.Cryptography;
using System.Text;
using Microsoft.IdentityModel.Tokens;
using ThakiiBackend.Api.Models;

namespace ThakiiBackend.Api.Services;

public interface ICustomTokenService
{
    string GenerateCustomToken(Dictionary<string, object?> firebaseUserData);
    ClaimsPrincipal? VerifyCustomToken(string token);
    CurrentUser? ExtractUser(ClaimsPrincipal? principal);
    bool IsSuperAdmin(string? email);
}

public class CustomTokenService : ICustomTokenService
{
    private readonly byte[] _secret;
    private readonly string _issuer;
    private readonly string _audience;
    private readonly int _expiryHours;
    private readonly string[] _superAdmins;
    private readonly ILogger<CustomTokenService> _logger;

    public CustomTokenService(IConfiguration config, ILogger<CustomTokenService> logger)
    {
        var secret = Environment.GetEnvironmentVariable("CUSTOM_TOKEN_SECRET") ?? config["Jwt:Secret"] ?? "thakii-custom-secret-key-2025";
        _secret = Encoding.UTF8.GetBytes(secret);
        _issuer = config["Jwt:Issuer"] ?? "thakii-backend";
        _audience = config["Jwt:Audience"] ?? "thakii-frontend";
        _expiryHours = int.Parse(config["Jwt:ExpiryHours"] ?? "72");
        _superAdmins = config.GetSection("SuperAdmins").Get<string[]>() ?? new[] { "ouday.khaled@gmail.com", "appsaawt@gmail.com" };
        _logger = logger;
    }

    public string GenerateCustomToken(Dictionary<string, object?> firebaseUserData)
    {
        var uid = (firebaseUserData.GetValueOrDefault("uid") ?? firebaseUserData.GetValueOrDefault("user_id") ?? firebaseUserData.GetValueOrDefault("sub"))?.ToString();
        var email = firebaseUserData.GetValueOrDefault("email")?.ToString();
        var name = firebaseUserData.GetValueOrDefault("name")?.ToString() ?? (email != null ? email.Split('@')[0] : "Unknown");
        var picture = firebaseUserData.GetValueOrDefault("picture")?.ToString() ?? "";
        var emailVerified = firebaseUserData.GetValueOrDefault("email_verified") is true;
        var isAdmin = email != null && _superAdmins.Contains(email);

        var now = DateTime.UtcNow;
        var expiry = now.AddHours(_expiryHours);
        var claims = new List<Claim>
        {
            new("user_id", uid ?? ""),
            new("email", email ?? ""),
            new("name", name),
            new("picture", picture ?? ""),
            new("email_verified", emailVerified.ToString().ToLower()),
            new("token_type", "custom_backend"),
            new("is_admin", isAdmin.ToString().ToLower()),
            new(JwtRegisteredClaimNames.Iat, DateTimeOffset.UtcNow.ToUnixTimeSeconds().ToString()),
            new(JwtRegisteredClaimNames.Exp, new DateTimeOffset(expiry).ToUnixTimeSeconds().ToString())
        };
        var key = new SymmetricSecurityKey(_secret);
        var creds = new SigningCredentials(key, SecurityAlgorithms.HmacSha256);
        var token = new JwtSecurityToken(_issuer, _audience, claims, now, expiry, creds);
        return new JwtSecurityTokenHandler().WriteToken(token);
    }

    public ClaimsPrincipal? VerifyCustomToken(string token)
    {
        try
        {
            var handler = new JwtSecurityTokenHandler();
            var validation = new TokenValidationParameters
            {
                ValidIssuer = _issuer,
                ValidAudience = _audience,
                IssuerSigningKey = new SymmetricSecurityKey(_secret),
                ValidateIssuer = true,
                ValidateAudience = true,
                ValidateLifetime = true,
                ClockSkew = TimeSpan.Zero
            };
            return handler.ValidateToken(token, validation, out _);
        }
        catch
        {
            return null;
        }
    }

    public CurrentUser? ExtractUser(ClaimsPrincipal? principal)
    {
        if (principal == null) return null;
        var uid = principal.FindFirst("user_id")?.Value ?? principal.FindFirst(ClaimTypes.NameIdentifier)?.Value;
        var email = principal.FindFirst("email")?.Value ?? principal.FindFirst(ClaimTypes.Email)?.Value;
        if (string.IsNullOrEmpty(uid) || string.IsNullOrEmpty(email)) return null;
        var isAdmin = principal.FindFirst("is_admin")?.Value?.ToLower() == "true" || (email != null && _superAdmins.Contains(email));
        return new CurrentUser
        {
            Uid = uid,
            Email = email,
            Name = principal.FindFirst("name")?.Value ?? email?.Split('@')[0],
            Picture = principal.FindFirst("picture")?.Value,
            EmailVerified = principal.FindFirst("email_verified")?.Value?.ToLower() == "true",
            IsAdmin = isAdmin
        };
    }

    public bool IsSuperAdmin(string? email) => !string.IsNullOrEmpty(email) && _superAdmins.Contains(email);
}
