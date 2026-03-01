using System.Security.Claims;
using Microsoft.IdentityModel.Tokens;
using System.IdentityModel.Tokens.Jwt;
using System.Text;
using ThakiiBackend.Api.Models;
using ThakiiBackend.Api.Services;

namespace ThakiiBackend.Api.Middleware;

public class AuthMiddleware
{
    private readonly RequestDelegate _next;
    private readonly IConfiguration _config;

    public AuthMiddleware(RequestDelegate next, IConfiguration config)
    {
        _next = next;
        _config = config;
    }

    public async Task InvokeAsync(HttpContext context, ICustomTokenService tokenService)
    {
        var authHeader = context.Request.Headers.Authorization.FirstOrDefault();
        if (!string.IsNullOrEmpty(authHeader) && authHeader.StartsWith("Bearer "))
        {
            var token = authHeader["Bearer ".Length..].Trim();
            var principal = tokenService.VerifyCustomToken(token);
            if (principal != null)
            {
                var user = tokenService.ExtractUser(principal);
                if (user != null)
                {
                    context.Items["CurrentUser"] = user;
                    context.Items["AuthPrincipal"] = principal;
                }
            }
        }
        await _next(context);
    }
}

public static class AuthMiddlewareExtensions
{
    public static IApplicationBuilder UseAuthMiddleware(this IApplicationBuilder app) =>
        app.UseMiddleware<AuthMiddleware>();
}
