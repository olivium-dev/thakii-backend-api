using Microsoft.AspNetCore.Mvc;
using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using System.Security.Cryptography;
using System.Text;
using ThakiiBackend.Api.Services;
using thakii.service.ServiceWallet;

namespace ThakiiBackend.Api.Controllers;

[ApiController]
[Route("auth")]
public class AuthController : ControllerBase
{
    private static string? GetClaim(ClaimsPrincipal? principal, string type) =>
        principal?.FindFirst(type)?.Value;

    private static Guid UidToHolderId(string uid)
    {
        var bytes = MD5.HashData(Encoding.UTF8.GetBytes(uid));
        return new Guid(bytes);
    }

    private readonly ICustomTokenService _tokenService;
    private readonly IConfiguration _config;
    private readonly ServiceWalletClient _walletClient;
    private readonly ILogger<AuthController> _logger;

    public AuthController(
        ICustomTokenService tokenService,
        IConfiguration config,
        ServiceWalletClient walletClient,
        ILogger<AuthController> logger)
    {
        _tokenService = tokenService;
        _config = config;
        _walletClient = walletClient;
        _logger = logger;
    }

    [HttpPost("login")]
    public async Task<IActionResult> Login()
    {
        var authHeader = Request.Headers.Authorization.FirstOrDefault();
        if (string.IsNullOrEmpty(authHeader) || !authHeader.StartsWith("Bearer "))
        {
            _logger.LogWarning("Auth login called without valid Authorization Bearer header.");
            return BadRequest(new { error = "No Firebase token provided" });
        }

        var firebaseToken = authHeader["Bearer ".Length..].Trim();
        _logger.LogInformation(
            "Auth login started. Received Firebase token with length {TokenLength} characters.",
            firebaseToken.Length);

        string? userId = null;
        string? email = null;

        try
        {
            var handler = new JwtSecurityTokenHandler();
            var token = handler.ReadJwtToken(firebaseToken);
            userId = token.Claims.FirstOrDefault(c => c.Type == "user_id" || c.Type == "sub")?.Value;
            email = token.Claims.FirstOrDefault(c => c.Type == "email")?.Value;

            _logger.LogInformation(
                "Parsed Firebase token. userId={UserId}, email={Email}",
                userId, email);

            if (string.IsNullOrEmpty(userId) || string.IsNullOrEmpty(email))
            {
                _logger.LogWarning(
                    "Auth login failed: missing required claims (userId or email). userId={UserId}, email={Email}",
                    userId, email);
                return BadRequest(new { error = "Invalid Firebase token data" });
            }

            var exp = token.Claims.FirstOrDefault(c => c.Type == "exp")?.Value;
            if (!string.IsNullOrEmpty(exp) && long.TryParse(exp, out var expUnix))
            {
                var expTime = DateTimeOffset.FromUnixTimeSeconds(expUnix);
                if (expTime.UtcDateTime < DateTime.UtcNow)
                {
                    _logger.LogWarning(
                        "Auth login failed: Firebase token expired for user {UserId}, email {Email}. Exp={ExpTimeUtc}",
                        userId, email, expTime.UtcDateTime);
                    return Unauthorized(new { error = "Firebase token expired" });
                }
            }

            var userData = new Dictionary<string, object?>
            {
                ["uid"] = userId,
                ["user_id"] = userId,
                ["email"] = email,
                ["name"] = token.Claims.FirstOrDefault(c => c.Type == "name")?.Value ?? email.Split('@')[0],
                ["picture"] = token.Claims.FirstOrDefault(c => c.Type == "picture")?.Value ?? "",
                ["email_verified"] = token.Claims.FirstOrDefault(c => c.Type == "email_verified")?.Value == "true",
                ["auth_time"] = token.Claims.FirstOrDefault(c => c.Type == "auth_time")?.Value
            };
            _logger.LogInformation(
                "Auth login building backend token payload for user {UserId}, email {Email}.",
                userId, email);

            var backendToken = _tokenService.GenerateCustomToken(userData);
            var superAdmins = _config.GetSection("SuperAdmins").Get<string[]>() ?? Array.Empty<string>();
            var isAdmin = superAdmins.Contains(email);

            _logger.LogInformation(
                "Generated backend token for user {UserId}. IsAdmin={IsAdmin}. Ensuring wallets...",
                userId, isAdmin);

            // Create wallet if user has none
            await EnsureWalletAsync(userId, userData["name"]?.ToString() ?? email);

            _logger.LogInformation(
                "Auth login finished successfully for user {UserId}, email {Email}.",
                userId, email);

            var holderId = UidToHolderId(userId);

            return Ok(new
            {
                success = true,
                backend_token = backendToken,
                expires_in_days = 30,
                user = new
                {
                    uid = userId,
                    holder_id = holderId.ToString(),
                    email,
                    name = userData["name"],
                    picture = userData["picture"],
                    is_admin = isAdmin
                },
                message = "Firebase login successful, use backend_token for all future requests"
            });
        }
        catch (Exception ex)
        {
            _logger.LogError(
                ex,
                "Auth login failed with exception for user {UserId}, email {Email}.",
                userId, email);

            return StatusCode(500, new { error = "Login failed", message = ex.Message });
        }
    }

    [HttpPost("exchange-token")]
    public IActionResult ExchangeToken()
    {
        // The middleware already verified the token if present
        var authHeader = Request.Headers.Authorization.FirstOrDefault();
        if (string.IsNullOrEmpty(authHeader) || !authHeader.StartsWith("Bearer "))
            return BadRequest(new { error = "No Firebase token provided" });

        var token = authHeader["Bearer ".Length..].Trim();

        try
        {
            // Check if this is already a custom backend token
            var principal = _tokenService.VerifyCustomToken(token);
            if (principal != null)
            {
                var tokenType = principal.FindFirst("token_type")?.Value;
                if (tokenType == "custom_backend")
                {
                    var exp = principal.FindFirst("exp")?.Value;
                    return BadRequest(new
                    {
                        error = "Token already custom",
                        message = "This is already a custom backend token",
                        expires_at = !string.IsNullOrEmpty(exp) && long.TryParse(exp, out var expVal) ? (object)expVal : exp,
                        token_type = "custom"
                    });
                }
            }

            // Decode Firebase token (without verification, like in /auth/login)
            var handler = new JwtSecurityTokenHandler();
            var jwtToken = handler.ReadJwtToken(token);

            var userId = jwtToken.Claims.FirstOrDefault(c => c.Type == "user_id" || c.Type == "sub")?.Value;
            var email = jwtToken.Claims.FirstOrDefault(c => c.Type == "email")?.Value;
            var name = jwtToken.Claims.FirstOrDefault(c => c.Type == "name")?.Value ?? email?.Split('@')[0] ?? "Unknown";
            var picture = jwtToken.Claims.FirstOrDefault(c => c.Type == "picture")?.Value;
            var emailVerified = jwtToken.Claims.FirstOrDefault(c => c.Type == "email_verified")?.Value == "true";

            if (string.IsNullOrEmpty(userId) || string.IsNullOrEmpty(email))
                return Unauthorized(new { error = "Invalid Firebase token", message = "Missing required claims" });

            var userData = new Dictionary<string, object?>
            {
                ["uid"] = userId,
                ["user_id"] = userId,
                ["email"] = email,
                ["name"] = name,
                ["picture"] = picture ?? "",
                ["email_verified"] = emailVerified
            };

            var customToken = _tokenService.GenerateCustomToken(userData);
            var superAdmins = _config.GetSection("SuperAdmins").Get<string[]>() ?? Array.Empty<string>();
            var isAdmin = superAdmins.Contains(email);

            var firebaseProvider = jwtToken.Claims.FirstOrDefault(c => c.Type == "firebase")?.Value;
            var holderId = UidToHolderId(userId);

            return Ok(new
            {
                success = true,
                message = "Token exchanged successfully",
                custom_token = customToken,
                expires_in_hours = 72,
                expires_at = DateTimeOffset.UtcNow.AddHours(72).ToUnixTimeSeconds(),
                user = new
                {
                    uid = userId,
                    holder_id = holderId.ToString(),
                    email,
                    name,
                    picture = picture ?? "",
                    email_verified = emailVerified,
                    is_admin = isAdmin,
                    firebase_provider = firebaseProvider
                },
                token_type = "custom_backend"
            });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Token exchange failed");
            return StatusCode(500, new { error = "Token exchange failed", message = ex.Message });
        }
    }

    [HttpGet("user")]
    public IActionResult GetUser()
    {
        var user = (Models.CurrentUser?)HttpContext.Items["CurrentUser"];
        if (user == null)
        {
            _logger.LogWarning("GetUser called but no CurrentUser in HttpContext.");
            return Unauthorized(new { error = "Authentication required", message = "No user data available" });
        }

        var principal = (ClaimsPrincipal?)HttpContext.Items["AuthPrincipal"];
        var exp = GetClaim(principal, "exp");
        var iat = GetClaim(principal, "iat");
        var tokenType = GetClaim(principal, "token_type") ?? "custom_backend";

        _logger.LogInformation(
            "GetUser called. uid={Uid}, email={Email}, tokenType={TokenType}, exp={Exp}, iat={Iat}",
            user.Uid, user.Email, tokenType, exp, iat);

        var holderId = !string.IsNullOrEmpty(user.Uid) ? UidToHolderId(user.Uid) : default;
        var userResponse = new Dictionary<string, object?>
        {
            ["uid"] = user.Uid,
            ["user_id"] = user.Uid,
            ["holder_id"] = holderId != default ? holderId.ToString() : null,
            ["email"] = user.Email,
            ["name"] = user.Name,
            ["picture"] = user.Picture,
            ["email_verified"] = user.EmailVerified,
            ["is_admin"] = user.IsAdmin
        };
        if (!string.IsNullOrEmpty(exp)) userResponse["token_expires_at"] = long.TryParse(exp, out var expVal) ? expVal : exp;
        if (!string.IsNullOrEmpty(iat)) userResponse["token_issued_at"] = long.TryParse(iat, out var iatVal) ? iatVal : iat;
        userResponse["token_type"] = tokenType;

        return Ok(new
        {
            success = true,
            user = userResponse,
            timestamp = DateTime.UtcNow.ToString("o")
        });
    }

    private async Task EnsureWalletAsync(string userId, string holderName)
    {
        var holderId = UidToHolderId(userId);
        _logger.LogInformation("Ensuring wallet for user {UserId} with holderId {HolderId}", userId, holderId);
        try
        {
            var existing = await _walletClient.WalletsAsync(holderId);
            var wallets = existing.Wallets?.ToList() ?? new List<Wallet>();
            var walletCount = wallets.Count;
            _logger.LogInformation("Wallet holder {HolderId} already exists with {WalletCount} wallet(s)", holderId, walletCount);

            // If the service returns an empty wallets list, treat it as "no wallets yet"
            // and create the holder + both wallets via POST /Wallet/holder/add (CreateWalletOwnerDto).
            if (walletCount == 0)
            {
                _logger.LogInformation(
                    "Wallet holder {HolderId} has empty wallets list. Creating holder + default wallets via /Wallet/holder/add.",
                    holderId);

                try
                {
                    var dto = new CreateWalletOwnerDto
                    {
                        WalletHolder = new AddWalletHolderRequest
                        {
                            HolderId = holderId,
                            HolderName = holderName,
                            HolderType = "USER"
                        },
                        Wallets = new List<AddWalletRequest>
                        {
                            new AddWalletRequest
                            {
                                CurrencyID = 1,
                                Type = "Credit",
                                Note = "To be used within the app"
                            },
                            new AddWalletRequest
                            {
                                CurrencyID = 2,
                                Type = "USD",
                                Note = "To be used to buy credits"
                            }
                        }
                    };

                    var response = await _walletClient.AddAsync(dto);
                    var createdWallets = response.Wallets?.Count ?? 0;
                    _logger.LogInformation(
                        "Created wallet holder {HolderId} with {WalletCount} wallet(s) for user {UserId} (empty-list case).",
                        holderId, createdWallets, userId);
                }
                catch (Exception e)
                {
                    _logger.LogError(e,
                        "Failed to create wallet holder {HolderId} with default wallets in empty-list case for user {UserId}",
                        holderId, userId);
                }

                return;
            }

            var hasCreditWallet = wallets.Any(w => w.CurrencyID == 1);
            var hasUsdWallet = wallets.Any(w => w.CurrencyID == 2);

            if (hasCreditWallet && hasUsdWallet)
            {
                _logger.LogInformation("Wallet holder {HolderId} already has both Credit (1) and USD (2) wallets. Nothing to create.", holderId);
            }
            else
            {
                _logger.LogInformation(
                    "Wallet holder {HolderId} missing required wallets (Credit={HasCredit}, USD={HasUsd}). Creating missing ones.",
                    holderId, hasCreditWallet, hasUsdWallet);

                if (!hasCreditWallet)
                {
                    try
                    {
                        var creditRequest = new AddWalletRequest
                        {
                            CurrencyID = 1,
                            Type = "Credit",
                            Note = "To be used within the app"
                        };
                        var creditWallet = await _walletClient.AddAsync(holderId, creditRequest);
                        _logger.LogInformation("Created Credit wallet {WalletId} for holder {HolderId}", creditWallet.WalletId, holderId);
                    }
                    catch (Exception e)
                    {
                        _logger.LogError(e, "Failed to create Credit wallet for holder {HolderId}", holderId);
                    }
                }

                if (!hasUsdWallet)
                {
                    try
                    {
                        var usdRequest = new AddWalletRequest
                        {
                            CurrencyID = 2,
                            Type = "USD",
                            Note = "To be used to buy credits"
                        };
                        var usdWallet = await _walletClient.AddAsync(holderId, usdRequest);
                        _logger.LogInformation("Created USD wallet {WalletId} for holder {HolderId}", usdWallet.WalletId, holderId);
                    }
                    catch (Exception e)
                    {
                        _logger.LogError(e, "Failed to create USD wallet for holder {HolderId}", holderId);
                    }
                }
            }
        }
        catch (ApiException ex) when (ex.StatusCode == 404)
        {
            // No wallet, create holder + default wallets (Credit + USD) similar to Rahmah social login
            _logger.LogInformation("Wallet holder {HolderId} not found (404). Creating holder and default wallets for user {UserId}", holderId, userId);
            try
            {
                var dto = new CreateWalletOwnerDto
                {
                    WalletHolder = new AddWalletHolderRequest
                    {
                        HolderId = holderId,
                        HolderName = holderName,
                        // Keep using the Thakii-specific holder type, but align wallets with Rahmah
                        HolderType = "USER"
                    },
                    Wallets = new List<AddWalletRequest>
                    {
                        new AddWalletRequest
                        {
                            CurrencyID = 1,
                            Type = "Credit",
                            Note = "To be used within the app"
                        },
                        new AddWalletRequest
                        {
                            CurrencyID = 2,
                            Type = "USD",
                            Note = "To be used to buy credits"
                        }
                    }
                };
                var response = await _walletClient.AddAsync(dto);
                var createdWallets = response.Wallets?.Count ?? 0;
                _logger.LogInformation("Created wallet holder {HolderId} with {WalletCount} wallet(s) for user {UserId}", holderId, createdWallets, userId);
            }
            catch (Exception e)
            {
                // Log but don't fail login
                _logger.LogError(e, "Failed to create wallet holder {HolderId} for user {UserId}", holderId, userId);
            }
        }
        catch (Exception e)
        {
            // Any unexpected error while checking wallet should not break login, but we log it
            _logger.LogError(e, "Unexpected error while ensuring wallet for user {UserId} with holderId {HolderId}", userId, holderId);
        }
    }
}
