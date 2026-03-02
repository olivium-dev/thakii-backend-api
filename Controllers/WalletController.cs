using Microsoft.AspNetCore.Mvc;
using thakii.service.ServiceWallet;
using WalletApiException = thakii.service.ServiceWallet.ApiException;

namespace ThakiiBackend.Api.Controllers;

[ApiController]
[Route("api/[controller]")]
public class WalletController : ControllerBase
{
    private readonly ServiceWalletClient _walletClient;
    private readonly ILogger<WalletController> _logger;

    public WalletController(ServiceWalletClient walletClient, ILogger<WalletController> logger)
    {
        _walletClient = walletClient;
        _logger = logger;
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
}

public class AppleIAPWebhookRequest
{
    public string UserId { get; set; } = string.Empty;
    public int CreditAmount { get; set; }
    public decimal Price { get; set; }
}

