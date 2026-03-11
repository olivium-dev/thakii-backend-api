using System.Security.Cryptography;
using System.Text;
using Microsoft.AspNetCore.Mvc;
using ThakiiBackend.Api.Models;
using thakii.service.ServiceWallet;
using WalletApiException = thakii.service.ServiceWallet.ApiException;

namespace ThakiiBackend.Api.Controllers;

[ApiController]
[Route("api/[controller]")]
public class WalletController : ControllerBase
{
    private readonly ServiceWalletClient _walletClient;
    private readonly ILogger<WalletController> _logger;

    private static readonly List<CreditPackage> Packages = new()
    {
        new CreditPackage { Id = "starter",  Name = "Starter",  Credits = 10,  Price = 4.99m,  Popular = false },
        new CreditPackage { Id = "standard", Name = "Standard", Credits = 50,  Price = 19.99m, Popular = true  },
        new CreditPackage { Id = "premium",  Name = "Premium",  Credits = 100, Price = 34.99m, Popular = false },
    };

    public WalletController(ServiceWalletClient walletClient, ILogger<WalletController> logger)
    {
        _walletClient = walletClient;
        _logger = logger;
    }

    private CurrentUser? CurrentUser => (CurrentUser?)HttpContext.Items["CurrentUser"];

    private static Guid UidToHolderId(string uid)
    {
        var bytes = MD5.HashData(Encoding.UTF8.GetBytes(uid));
        return new Guid(bytes);
    }

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

    private static bool ValidateAppleIAPWebhook(AppleIAPWebhookRequest request)
    {
        if (request == null)
            return false;
        if (string.IsNullOrWhiteSpace(request.UserId))
            return false;
        return true;
    }

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
}

