using System.Collections.Concurrent;
using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using System.Security.Cryptography;
using System.Text;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.RateLimiting;
using Microsoft.Extensions.Caching.Memory;
using Microsoft.IdentityModel.Tokens;
using Newtonsoft.Json.Linq;
using ThakiiBackend.Api.Models;
using thakii.service.ServiceWallet;
using saawt.service.ServiceUnifiedPayment;
using WalletApiException = thakii.service.ServiceWallet.ApiException;
using UnifiedPaymentApiException = saawt.service.ServiceUnifiedPayment.ApiException;

namespace ThakiiBackend.Api.Controllers;

[ApiController]
[Route("api/[controller]")]
public class WalletController : ControllerBase
{
    private readonly ServiceWalletClient _walletClient;
    private readonly ServiceUnifiedPaymentGatewayClient _paymentClient;
    private readonly ILogger<WalletController> _logger;
    private readonly IMemoryCache _sessionCache;
    private readonly byte[] _jwtSecret;
    private readonly byte[] _checkoutJwtSecret;

    // In-process guard: prevents two concurrent requests in the same process from
    // double-crediting the same payment. Supplemented by the durable wallet_credited_at
    // field on the payment record (checked below), which survives process restarts.
    private static readonly ConcurrentDictionary<string, byte> _creditedPayments = new();

    private CurrentUser? CurrentUser => (CurrentUser?)HttpContext.Items["CurrentUser"];

    private static readonly List<CreditPackage> Packages = new()
    {
        new CreditPackage { Id = "starter",  Name = "Starter",  Credits = 10,  Price = 4.99m,  Popular = false, Currency = "USD" },
        new CreditPackage { Id = "standard", Name = "Standard", Credits = 50,  Price = 19.99m, Popular = true,  Currency = "USD" },
        new CreditPackage { Id = "premium",  Name = "Premium",  Credits = 100, Price = 34.99m, Popular = false, Currency = "USD" },
    };

    public WalletController(
        ServiceWalletClient walletClient,
        ServiceUnifiedPaymentGatewayClient paymentClient,
        IMemoryCache sessionCache,
        IConfiguration config,
        ILogger<WalletController> logger)
    {
        _walletClient = walletClient;
        _paymentClient = paymentClient;
        _sessionCache = sessionCache;
        _logger = logger;

        var authSecret = Environment.GetEnvironmentVariable("CUSTOM_TOKEN_SECRET")
                         ?? config["Jwt:Secret"]
                         ?? throw new InvalidOperationException(
                             "JWT secret must be configured via CUSTOM_TOKEN_SECRET env var or Jwt:Secret in appsettings.");
        _jwtSecret = Encoding.UTF8.GetBytes(authSecret);

        // Checkout sessions use a dedicated signing key so that a compromised auth
        // token cannot be mistaken for a valid checkout session and vice versa.
        var checkoutSecret = Environment.GetEnvironmentVariable("CHECKOUT_SESSION_SECRET")
                             ?? config["Jwt:CheckoutSecret"]
                             ?? authSecret;  // safe fallback — same entropy, different audience
        _checkoutJwtSecret = Encoding.UTF8.GetBytes(checkoutSecret);
    }

    /// <summary>Maps Firebase UID to the deterministic holder GUID used by the wallet service.</summary>
    private static Guid UidToHolderId(string uid)
    {
        var bytes = MD5.HashData(Encoding.UTF8.GetBytes(uid));
        return new Guid(bytes);
    }

    /// <summary>
    /// Get the current user's wallet (holder and wallets). HolderId is derived from the authenticated user's token (Firebase UID).
    /// </summary>
    [HttpGet]
    [ProducesResponseType(typeof(GetHolderWallets), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status401Unauthorized)]
    [ProducesResponseType(StatusCodes.Status500InternalServerError)]
    public async Task<IActionResult> GetMyWallet()
    {
        var user = CurrentUser;
        if (user == null || string.IsNullOrEmpty(user.Uid))
            return Unauthorized(new { error = "Authentication required" });

        var holderId = UidToHolderId(user.Uid);
        try
        {
            var result = await _walletClient.WalletsAsync(holderId);
            return Ok(result);
        }
        catch (WalletApiException ex)
        {
            _logger.LogError(ex, "Wallet API error getting wallets for user {UserId}, holderId {HolderId}", user.Uid, holderId);
            return StatusCode(ex.StatusCode, new { error = ex.Message });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Unexpected error fetching balance for user {Uid}", CurrentUser.Uid);
            return StatusCode(500, new { error = "Internal server error" });
        }
    }

    /// <summary>
    /// Get the current user's credit balance (credits only). Used by thakii-frontend for display.
    /// </summary>
    [HttpGet("balance")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status401Unauthorized)]
    [ProducesResponseType(StatusCodes.Status500InternalServerError)]
    public async Task<IActionResult> GetBalance()
    {
        if (CurrentUser?.Uid == null)
            return Unauthorized(new { error = "Authentication required" });

        try
        {
            var holderId = UidToHolderId(CurrentUser.Uid);
            var userWalletHolder = await _walletClient.WalletsAsync(holderId);

            var creditWallet = userWalletHolder.Wallets?.FirstOrDefault(w => w.CurrencyID == 1);
            var balance = creditWallet?.Amount ?? 0;

            return Ok(new { credits = balance });
        }
        catch (WalletApiException ex)
        {
            _logger.LogError(ex, "Wallet API error fetching balance for user {Uid}", CurrentUser.Uid);
            return StatusCode(ex.StatusCode, new { error = "Failed to retrieve credit balance" });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Unexpected error fetching balance for user {Uid}", CurrentUser.Uid);
            return StatusCode(500, new { error = "Internal server error" });
        }
    }

    [HttpGet("packages")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    public IActionResult GetPackages()
    {
        return Ok(new { packages = Packages });
    }

    /// <summary>
    /// Creates a checkout session and returns a short-lived opaque exchange code.
    /// The code is a single-use UUID that expires in 15 minutes — no sensitive
    /// data ever touches the URL. The payment website exchanges it once for the
    /// session payload via POST /checkout-session/exchange.
    /// </summary>
    [HttpPost("checkout-session")]
    [EnableRateLimiting("checkout")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    [ProducesResponseType(StatusCodes.Status401Unauthorized)]
    public IActionResult CreateCheckoutSession([FromBody] CreateCheckoutSessionRequest request)
    {
        if (CurrentUser?.Uid == null)
            return Unauthorized(new { error = "Authentication required" });

        var package_ = Packages.FirstOrDefault(p => p.Id == request.PackageId);
        if (package_ == null)
            return BadRequest(new { error = $"Unknown package: {request.PackageId}" });

        var code = Guid.NewGuid().ToString("N");  // 32-char hex — opaque, unpredictable

        var sessionData = new CheckoutSessionPayload
        {
            ProjectId     = "thakii",
            UserId        = CurrentUser.Uid,
            CustomerName  = CurrentUser.Name ?? "",
            CustomerEmail = CurrentUser.Email ?? "",
            PackageId     = package_.Id,
            PackageName   = package_.Name,
            Amount        = package_.Price.ToString(System.Globalization.CultureInfo.InvariantCulture),
            Currency      = package_.Currency,
            Credits       = package_.Credits.ToString(),
            CallbackUrl   = request.CallbackUrl ?? "",
        };

        _sessionCache.Set($"checkout:{code}", sessionData, TimeSpan.FromMinutes(15));

        _logger.LogInformation("Checkout code issued for user {Uid}, package {Pkg}", CurrentUser.Uid, package_.Id);

        return Ok(new { code });
    }

    /// <summary>
    /// Exchanges a one-time checkout code for the session payload.
    /// The code is deleted on first use — replaying it returns 404.
    /// No authentication required; the code itself proves authorization.
    /// </summary>
    [HttpPost("checkout-session/exchange")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public IActionResult ExchangeCheckoutCode([FromBody] ExchangeCheckoutCodeRequest request)
    {
        var key = $"checkout:{request.Code}";

        if (!_sessionCache.TryGetValue(key, out CheckoutSessionPayload? sessionData) || sessionData == null)
        {
            _logger.LogWarning("Checkout code exchange failed — not found or expired. code={Code}", request.Code);
            return NotFound(new { error = "Checkout session not found or has expired." });
        }

        _sessionCache.Remove(key);  // single-use: invalidate immediately after exchange

        return Ok(new
        {
            project_id     = sessionData.ProjectId,
            user_id        = sessionData.UserId,
            customer_name  = sessionData.CustomerName,
            customer_email = sessionData.CustomerEmail,
            package_id     = sessionData.PackageId,
            package_name   = sessionData.PackageName,
            amount         = sessionData.Amount,
            currency       = sessionData.Currency,
            credits        = sessionData.Credits,
            callback_url   = sessionData.CallbackUrl,
        });
    }

    /// <summary>
    /// Legacy: verifies a signed JWT checkout session token.
    /// Kept for backward compatibility — new callers should use the code flow above.
    /// </summary>
    [HttpGet("checkout-session/{token}")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public IActionResult ResolveCheckoutSession(string token)
    {
        try
        {
            var handler = new JwtSecurityTokenHandler();
            var validation = new TokenValidationParameters
            {
                ValidIssuer = "thakii-backend",
                ValidAudience = "thakii-payment",
                IssuerSigningKey = new SymmetricSecurityKey(_checkoutJwtSecret),
                ValidateIssuer = true,
                ValidateAudience = true,
                ValidateLifetime = true,
                ClockSkew = TimeSpan.Zero,
            };
            var principal = handler.ValidateToken(token, validation, out _);

            string? Claim(string type) => principal.FindFirst(type)?.Value;

            return Ok(new
            {
                project_id     = "thakii",
                user_id        = Claim("user_id"),
                customer_name  = Claim("name"),
                customer_email = Claim("email"),
                package_id     = Claim("package_id"),
                package_name   = Claim("package_name"),
                amount         = Claim("amount"),
                currency       = Claim("currency"),
                credits        = Claim("credits"),
                callback_url   = Claim("callback_url"),
            });
        }
        catch (SecurityTokenExpiredException)
        {
            return BadRequest(new { error = "Checkout session has expired. Please try again." });
        }
        catch
        {
            return BadRequest(new { error = "Invalid checkout session." });
        }
    }

    // MOCKED: This endpoint simulates a credit purchase without a real payment gateway.
    // In production, replace with Stripe Checkout or equivalent payment flow.
    [HttpPost("packages/{packageId}/purchase")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    [ProducesResponseType(StatusCodes.Status401Unauthorized)]
    [ProducesResponseType(StatusCodes.Status500InternalServerError)]
    public async Task<IActionResult> PurchasePackage(string packageId)
    {
        if (CurrentUser?.Uid == null)
            return Unauthorized(new { error = "Authentication required" });

        var package_ = Packages.FirstOrDefault(p => p.Id == packageId);
        if (package_ == null)
            return BadRequest(new { error = $"Unknown package: {packageId}" });

        try
        {
            var holderId = UidToHolderId(CurrentUser.Uid);

            var systemWallet = await _walletClient.SystemWalletAsync();
            var systemCreditWalletId = systemWallet.Wallets.FirstOrDefault(w => w.Type == "__SYSTEM__")?.WalletId;
            var systemPrimaryWalletId = systemWallet.Wallets.FirstOrDefault(w => w.Type == "__SYSTEM__PRIMARY__")?.WalletId;

            if (systemCreditWalletId == null || systemPrimaryWalletId == null)
            {
                _logger.LogError("System wallet IDs not found for package purchase");
                return StatusCode(500, new { error = "System wallet configuration error" });
            }

            var userWalletHolder = await _walletClient.WalletsAsync(holderId);
            if (userWalletHolder.WalletHolder == null)
                return StatusCode(500, new { error = "User wallet not found" });

            var userCreditWallet = userWalletHolder.Wallets.FirstOrDefault(w => w.CurrencyID == 1);
            var userPrimaryWallet = userWalletHolder.Wallets.FirstOrDefault(w => w.CurrencyID == 2);

            if (userCreditWallet == null || userPrimaryWallet == null)
                return StatusCode(500, new { error = "User wallets not fully initialized" });

            var initiateRequest = new TransactionRequest
            {
                ServiceName = "ThakiiBackend",
                Tag = "WebPurchase_MOCKED",
                Notes = $"MOCKED Web Purchase - Package: {package_.Id}, Credits: {package_.Credits}, Price: {package_.Price}, User: {CurrentUser.Uid}",
                Transactions = new List<TransactionDetailsRequest>
                {
                    new()
                    {
                        SourceWalletId = (Guid)systemPrimaryWalletId,
                        DestinationWalletId = (Guid)userPrimaryWallet.WalletId,
                        Amount = (double)package_.Price
                    },
                    new()
                    {
                        SourceWalletId = (Guid)userPrimaryWallet.WalletId,
                        DestinationWalletId = (Guid)systemCreditWalletId,
                        Amount = package_.Credits
                    },
                    new()
                    {
                        SourceWalletId = (Guid)systemCreditWalletId,
                        DestinationWalletId = (Guid)userCreditWallet.WalletId,
                        Amount = package_.Credits
                    }
                }
            };

            var transaction = await _walletClient.InitiateAsync(initiateRequest);
            await _walletClient.ExecuteAsync(transaction.TransactionHeader.TxId);

            var updatedHolder = await _walletClient.WalletsAsync(holderId);
            var newBalance = updatedHolder.Wallets?.FirstOrDefault(w => w.CurrencyID == 1)?.Amount ?? 0;

            return Ok(new
            {
                success = true,
                credits_added = package_.Credits,
                new_balance = newBalance,
                transaction_id = transaction.TransactionHeader.TxId.ToString()
            });
        }
        catch (WalletApiException ex)
        {
            _logger.LogError(ex, "Wallet API error during package purchase for user {Uid}", CurrentUser.Uid);
            return StatusCode(ex.StatusCode, new { error = "Purchase failed" });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Unexpected error during package purchase for user {Uid}", CurrentUser.Uid);
            return StatusCode(500, new { error = "Internal server error" });
        }
    }

    /// <summary>
    /// Validates the Apple IAP webhook request (required: UserId).
    /// </summary>
    private static bool ValidateAppleIAPWebhook(AppleIAPWebhookRequest request)
    {
        if (request == null)
            return false;
        if (string.IsNullOrWhiteSpace(request.UserId))
            return false;
        return true;
    }

    /// <summary>
    /// Webhook used after Apple has already successfully charged the user.
    /// It credits the user's wallets following the same 3-leg flow as in saawt-gateway.
    /// </summary>
    [HttpPost("webhook/apple-iap")]
    [ProducesResponseType(typeof(Transaction), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    [ProducesResponseType(StatusCodes.Status500InternalServerError)]
    public async Task<IActionResult> AppleIAPWebhook([FromBody] AppleIAPWebhookRequest request)
    {
        if (request == null)
            return BadRequest(new { error = "Request body is required." });

        string? userId = null;

        try
        {
            if (!ValidateAppleIAPWebhook(request))
                return BadRequest(new { error = "Invalid webhook: UserId required" });

            userId = request.UserId;
            var creditAmount = request.CreditAmount;
            var usdAmount = (double)request.Price;

            // Initialize transaction (same pattern as saawt-gateway StartPackagePayment)
            var systemWallet = await _walletClient.SystemWalletAsync();

            var systemCreditWalletId = systemWallet.Wallets.FirstOrDefault(wallet => wallet.Type == "__SYSTEM__")?.WalletId;
            var systemPrimaryWalletId = systemWallet.Wallets.FirstOrDefault(wallet => wallet.Type == "__SYSTEM__PRIMARY__")?.WalletId;

            if (systemCreditWalletId == null || systemPrimaryWalletId == null)
            {
                _logger.LogError("System wallet ID or primary system wallet ID not found.");
                return StatusCode(500, new { error = "System wallet ID or primary system wallet ID not found." });
            }

            var userWalletHolder = await _walletClient.WalletsAsync(Guid.Parse(userId));

            if (userWalletHolder.WalletHolder == null)
            {
                _logger.LogError("User wallet holder not found for user {UserId}", userId);
                return StatusCode(500, new { error = "User wallet holder not found." });
            }

            var userCreditWallet = userWalletHolder.Wallets.FirstOrDefault(wallet => wallet.CurrencyID == 1);
            var userPrimaryWallet = userWalletHolder.Wallets.FirstOrDefault(wallet => wallet.CurrencyID == 2);

            if (userCreditWallet == null || userPrimaryWallet == null)
            {
                _logger.LogError("User credit or primary wallet not found for user {UserId}", userId);
                return StatusCode(500, new { error = "User credit or primary wallet not found." });
            }

            // Same 3-leg flow as StartPackagePayment:
            // 1) Fund user primary from system primary
            // 2) Move primary funds to system credit
            // 3) Grant credits from system credit to user credit
            var initiateRequest = new TransactionRequest
            {
                ServiceName = "ThakiiBackend",
                Tag = "AppleIAP",
                Notes = $"Apple IAP Purchase - UserId: {userId}, Credits: {creditAmount}, Price: {request.Price}",
                Transactions = new List<TransactionDetailsRequest>
                {
                    new()
                    {
                        SourceWalletId = (Guid)systemPrimaryWalletId,
                        DestinationWalletId = (Guid)userPrimaryWallet.WalletId,
                        Amount = usdAmount
                    },
                    new()
                    {
                        SourceWalletId = (Guid)userPrimaryWallet.WalletId,
                        DestinationWalletId = (Guid)systemCreditWalletId,
                        Amount = (double)creditAmount
                    },
                    new()
                    {
                        SourceWalletId = (Guid)systemCreditWalletId,
                        DestinationWalletId = (Guid)userCreditWallet.WalletId,
                        Amount = (double)creditAmount
                    }
                }
            };

            var transaction = await _walletClient.InitiateAsync(initiateRequest);

            // Apple already charged; execute immediately (no payment gateway step)
            await _walletClient.ExecuteAsync(transaction.TransactionHeader.TxId);

            return Ok(transaction);
        }
        catch (WalletApiException ex)
        {
            _logger.LogError(ex, "Wallet API error in AppleIAPWebhook for user {UserId}", userId);
            return StatusCode(ex.StatusCode, new { error = ex.Message });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Unexpected error in AppleIAPWebhook for user {UserId}", userId);
            return StatusCode(500, new { error = "Internal server error", details = ex.Message });
        }
    }

    /// <summary>
    /// Webhook called after a successful external payment. Accepts only a PaymentId,
    /// then verifies the payment server-side with the unified payment gateway and
    /// extracts trusted metadata (user_id, credit_amount, price) from the gateway's
    /// response — never from the caller.
    /// </summary>
    [HttpPost("webhook/unified-payment")]
    [ProducesResponseType(typeof(Transaction), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    [ProducesResponseType(StatusCodes.Status409Conflict)]
    [ProducesResponseType(StatusCodes.Status500InternalServerError)]
    public async Task<IActionResult> UnifiedPaymentWebhook([FromBody] UnifiedPaymentGatewayWebhookRequest request)
    {
        if (request == null || string.IsNullOrWhiteSpace(request.PaymentId))
        {
            _logger.LogWarning("UnifiedPaymentWebhook called with missing PaymentId.");
            return BadRequest(new { error = "PaymentId is required." });
        }

        var paymentId = request.PaymentId;

        // Fast in-process guard: prevents concurrent requests in the same process from
        // double-crediting. This is supplemented below by the gateway's wallet_credited_at
        // field which survives process restarts.
        if (!_creditedPayments.TryAdd(paymentId, 0))
        {
            _logger.LogInformation("Payment {PaymentId} already credited (in-process guard), returning 409.", paymentId);
            return Conflict(new { error = "Payment already credited.", payment_id = paymentId });
        }

        string? userId = null;

        try
        {
            // 1) Verify the payment with the unified payment gateway
            var paymentDetail = await _paymentClient.GetPaymentAsync(paymentId);
            var payment = paymentDetail.Data;

            // Durable idempotency: the gateway sets wallet_credited_at atomically when the
            // webhook fires. If it is already set, this call is a duplicate — reject it even
            // after a process restart (the in-process dict above is cleared on restart).
            if (payment.AdditionalProperties.TryGetValue("wallet_credited_at", out var creditedAt)
                && creditedAt != null
                && creditedAt.ToString() != "")
            {
                _creditedPayments.TryRemove(paymentId, out _);
                _logger.LogInformation("Payment {PaymentId} already credited by gateway webhook (wallet_credited_at={At}), returning 409.", paymentId, creditedAt);
                return Conflict(new { error = "Payment already credited.", payment_id = paymentId });
            }

            if (payment.Status != PaymentStatus.Paid && payment.Status != PaymentStatus.Authorized)
            {
                _creditedPayments.TryRemove(paymentId, out _);
                _logger.LogWarning(
                    "Payment {PaymentId} has non-successful status '{Status}'.",
                    paymentId, payment.Status);
                return BadRequest(new { error = $"Payment is not successful (status: {payment.Status}).", payment_id = paymentId });
            }

            // 2) Extract trusted metadata from the gateway-verified payment
            if (!payment.AdditionalProperties.TryGetValue("metadata", out var metadataRaw) || metadataRaw == null)
            {
                _creditedPayments.TryRemove(paymentId, out _);
                _logger.LogError("Payment {PaymentId} has no metadata attached.", paymentId);
                return BadRequest(new { error = "Payment metadata is missing. Cannot determine crediting details." });
            }

            var metadata = metadataRaw as JObject ?? JObject.FromObject(metadataRaw);
            userId = metadata["user_id"]?.ToString();
            var creditAmount = metadata["credit_amount"]?.ToObject<double>() ?? 0;
            var price = payment.Amount;

            if (string.IsNullOrWhiteSpace(userId) || creditAmount <= 0)
            {
                _creditedPayments.TryRemove(paymentId, out _);
                _logger.LogError(
                    "Payment {PaymentId} metadata is incomplete: user_id='{UserId}', credit_amount={CreditAmount}.",
                    paymentId, userId, creditAmount);
                return BadRequest(new { error = "Payment metadata is incomplete (user_id and credit_amount required)." });
            }

            _logger.LogInformation(
                "UnifiedPaymentWebhook verified payment {PaymentId}: UserId='{UserId}', Credits={Credits}, Amount={Amount}",
                paymentId, userId, creditAmount, price);

            // 3) Convert Firebase UID → deterministic wallet holder GUID
            var holderId = UidToHolderId(userId);

            var systemWallet = await _walletClient.SystemWalletAsync();

            var systemCreditWalletId = systemWallet.Wallets
                .FirstOrDefault(wallet => wallet.Type == "__SYSTEM__")?.WalletId;
            var systemPrimaryWalletId = systemWallet.Wallets
                .FirstOrDefault(wallet => wallet.Type == "__SYSTEM__PRIMARY__")?.WalletId;

            if (systemCreditWalletId == null || systemPrimaryWalletId == null)
            {
                _creditedPayments.TryRemove(paymentId, out _);
                _logger.LogError("System wallet IDs not found.");
                return StatusCode(500, new { error = "System wallet configuration error." });
            }

            var userWalletHolder = await _walletClient.WalletsAsync(holderId);

            if (userWalletHolder.WalletHolder == null)
            {
                _creditedPayments.TryRemove(paymentId, out _);
                _logger.LogError("User wallet holder not found for user {UserId} (holder {HolderId}).", userId, holderId);
                return StatusCode(500, new { error = "User wallet holder not found." });
            }

            var userCreditWallet = userWalletHolder.Wallets
                .FirstOrDefault(wallet => wallet.CurrencyID == 1);
            var userPrimaryWallet = userWalletHolder.Wallets
                .FirstOrDefault(wallet => wallet.CurrencyID == 2);

            if (userCreditWallet == null || userPrimaryWallet == null)
            {
                _creditedPayments.TryRemove(paymentId, out _);
                _logger.LogError("User credit or primary wallet not found for user {UserId}.", userId);
                return StatusCode(500, new { error = "User wallets not fully initialized." });
            }

            // 4) Execute the 3-step wallet transaction
            var initiateRequest = new TransactionRequest
            {
                ServiceName = "ThakiiBackend",
                Tag = "UnifiedPaymentGateway",
                Notes = $"Verified payment {paymentId} - UserId: {userId}, Credits: {creditAmount}, Amount: {price}",
                Transactions = new List<TransactionDetailsRequest>
                {
                    new()
                    {
                        SourceWalletId = (Guid)systemPrimaryWalletId,
                        DestinationWalletId = (Guid)userPrimaryWallet.WalletId,
                        Amount = price
                    },
                    new()
                    {
                        SourceWalletId = (Guid)userPrimaryWallet.WalletId,
                        DestinationWalletId = (Guid)systemCreditWalletId,
                        Amount = creditAmount
                    },
                    new()
                    {
                        SourceWalletId = (Guid)systemCreditWalletId,
                        DestinationWalletId = (Guid)userCreditWallet.WalletId,
                        Amount = creditAmount
                    }
                }
            };

            var transaction = await _walletClient.InitiateAsync(initiateRequest);
            await _walletClient.ExecuteAsync(transaction.TransactionHeader.TxId);

            _logger.LogInformation("Payment {PaymentId} credited successfully. TxId={TxId}", paymentId, transaction.TransactionHeader.TxId);

            return Ok(transaction);
        }
        catch (UnifiedPaymentApiException ex)
        {
            _creditedPayments.TryRemove(paymentId, out _);
            _logger.LogError(ex, "Unified payment gateway error verifying payment {PaymentId}.", paymentId);
            return StatusCode(ex.StatusCode, new { error = $"Failed to verify payment: {ex.Message}" });
        }
        catch (WalletApiException ex)
        {
            _creditedPayments.TryRemove(paymentId, out _);
            _logger.LogError(ex, "Wallet API error in UnifiedPaymentWebhook for user {UserId}, payment {PaymentId}.", userId, paymentId);
            return StatusCode(ex.StatusCode, new { error = ex.Message });
        }
        catch (Exception ex)
        {
            _creditedPayments.TryRemove(paymentId, out _);
            _logger.LogError(ex, "Unexpected error in UnifiedPaymentWebhook for payment {PaymentId}.", paymentId);
            return StatusCode(500, new { error = "Internal server error" });
        }
    }
}

public class AppleIAPWebhookRequest
{
    public string UserId { get; set; } = string.Empty;
    public int CreditAmount { get; set; }
    public decimal Price { get; set; }
}

public class CreditPackage
{
    public string Id { get; set; } = string.Empty;
    public string Name { get; set; } = string.Empty;
    public int Credits { get; set; }
    public decimal Price { get; set; }
    public bool Popular { get; set; }
    /// <summary>
    /// ISO currency code (e.g. KWD, SAR, USD) for this package.
    /// </summary>
    public string Currency { get; set; } = "USD";
}

public class CreateCheckoutSessionRequest
{
    public string PackageId { get; set; } = string.Empty;
    public string? CallbackUrl { get; set; }
}

public class ExchangeCheckoutCodeRequest
{
    public string Code { get; set; } = string.Empty;
}

public class CheckoutSessionPayload
{
    public string ProjectId     { get; set; } = string.Empty;
    public string UserId        { get; set; } = string.Empty;
    public string CustomerName  { get; set; } = string.Empty;
    public string CustomerEmail { get; set; } = string.Empty;
    public string PackageId     { get; set; } = string.Empty;
    public string PackageName   { get; set; } = string.Empty;
    public string Amount        { get; set; } = string.Empty;
    public string Currency      { get; set; } = string.Empty;
    public string Credits       { get; set; } = string.Empty;
    public string CallbackUrl   { get; set; } = string.Empty;
}
