using System.Security.Cryptography;
using System.Text;
using Microsoft.AspNetCore.Mvc;
using ThakiiBackend.Api.Models;
using thakii.service.ServiceInAppPurchase;
using thakii.service.ServiceWallet;
using InAppPurchaseApiException = thakii.service.ServiceInAppPurchase.ApiException;
using WalletApiException = thakii.service.ServiceWallet.ApiException;

namespace ThakiiBackend.Api.Controllers;

[ApiController]
[Route("api/[controller]")]
[Produces("application/json")]
public class InAppPurchaseController : ControllerBase
{
    private readonly ServiceInAppPurchaseClient _inAppPurchaseClient;
    private readonly ServiceWalletClient _walletClient;
    private readonly ILogger<InAppPurchaseController> _logger;

    public InAppPurchaseController(
        ServiceInAppPurchaseClient inAppPurchaseClient,
        ServiceWalletClient walletClient,
        ILogger<InAppPurchaseController> logger)
    {
        _inAppPurchaseClient = inAppPurchaseClient;
        _walletClient = walletClient;
        _logger = logger;
    }

    private CurrentUser? CurrentUser => (CurrentUser?)HttpContext.Items["CurrentUser"];

    private static Guid UidToHolderId(string uid)
    {
        var bytes = MD5.HashData(Encoding.UTF8.GetBytes(uid));
        return new Guid(bytes);
    }

    /// <summary>
    /// Handle Apple Server Notifications
    /// </summary>
    /// <remarks>
    /// Handle Apple App Store Server Notifications.
    ///
    /// Apple sends a webhook with a signedPayload (JWT) containing:
    /// - notificationType (e.g., ONE_TIME_CHARGE)
    /// - signedTransactionInfo (nested JWT with transaction details)
    ///
    /// Flow:
    /// 1. Apple sends webhook when user completes purchase
    /// 2. We decode the JWTs to extract transaction details
    /// 3. We find the stored purchase context (wallet_id)
    /// 4. We call wallet API to add credits to user's wallet
    /// 5. We mark purchase as completed and return 200 OK to Apple
    /// </remarks>
    [HttpPost("webhooks/apple-server-notifications")]
    [ProducesResponseType(typeof(object), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    [ProducesResponseType(StatusCodes.Status422UnprocessableEntity)]
    [ProducesResponseType(StatusCodes.Status500InternalServerError)]
    public async Task<IActionResult> HandleAppleWebhook([FromBody] AppleWebhookPayload request)
    {
        try
        {
            if (request == null || string.IsNullOrEmpty(request.SignedPayload))
            {
                _logger.LogWarning("Received Apple webhook with missing or empty signedPayload");
                return BadRequest(new { error = "Invalid webhook payload: signedPayload is required" });
            }

            _logger.LogInformation("Received Apple webhook with signedPayload (length: {PayloadLength})",
                request.SignedPayload.Length);

            var response = await _inAppPurchaseClient.Handle_apple_webhookAsync(request);

            _logger.LogInformation("Successfully processed Apple webhook");

            return Ok(response);
        }
        catch (InAppPurchaseApiException ex)
        {
            _logger.LogError(ex, "Apple webhook processing failed with status {StatusCode}: {Message}",
                ex.StatusCode, ex.Message);
            return StatusCode(ex.StatusCode, new { error = ex.Message });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Unexpected error processing Apple webhook");
            return StatusCode(500, new { error = "Internal server error", details = ex.Message });
        }
    }

    /// <summary>
    /// Initiate Purchase
    /// </summary>
    /// <remarks>
    /// Initiate purchase context before user starts Apple purchase.
    /// This endpoint should be called by your frontend BEFORE the user
    /// initiates the Apple in-app purchase. It stores the user's walletID
    /// so it can be retrieved when Apple sends the webhook.
    ///
    /// Flow:
    /// 1. Frontend calls this endpoint with user context
    /// 2. User initiates Apple purchase in the app
    /// 3. Apple sends webhook to /apple-server-notifications
    /// 4. Webhook handler retrieves stored context and processes purchase
    /// </remarks>
    [HttpPost("purchases/initiate")]
    [ProducesResponseType(typeof(PurchaseInitiationResponse), StatusCodes.Status201Created)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    [ProducesResponseType(StatusCodes.Status401Unauthorized)]
    [ProducesResponseType(StatusCodes.Status422UnprocessableEntity)]
    [ProducesResponseType(StatusCodes.Status500InternalServerError)]
    public async Task<IActionResult> InitiatePurchase()
    {
        try
        {
            if (CurrentUser == null)
            {
                _logger.LogWarning("InitiatePurchase called without authenticated user");
                return Unauthorized(new { error = "Authentication required" });
            }

            var holderId = UidToHolderId(CurrentUser.Uid!);

            var userWalletHolder = await _walletClient.WalletsAsync(holderId);
            if (userWalletHolder.WalletHolder == null)
            {
                _logger.LogError("User wallet holder not found for user {UserId}", CurrentUser.Uid);
                return StatusCode(500, new { error = "User wallet holder not found." });
            }

            var userCreditWallet = userWalletHolder.Wallets?.FirstOrDefault(wallet => wallet.CurrencyID == 1);
            if (userCreditWallet == null)
            {
                _logger.LogError("User credit wallet not found for user {UserId}", CurrentUser.Uid);
                return StatusCode(500, new { error = "User credit wallet not found." });
            }

            _logger.LogInformation("Found user credit wallet - WalletID: {WalletId}, CurrencyID: {CurrencyID}, Amount: {Amount}",
                userCreditWallet.WalletId, userCreditWallet.CurrencyID, userCreditWallet.Amount);

            var serviceRequest = new PurchaseInitiationRequest
            {
                User_id = CurrentUser.Uid!,
                Wallet_id = userCreditWallet.WalletId.ToString()
            };

            _logger.LogInformation("Initiating purchase for user {UserId}, sending credit wallet ID: {WalletId}",
                serviceRequest.User_id, serviceRequest.Wallet_id);

            var response = await _inAppPurchaseClient.Initiate_purchaseAsync(serviceRequest);

            _logger.LogInformation("Successfully initiated purchase with context ID {PurchaseContextId} for user {UserId}",
                response.Purchase_context_id, CurrentUser.Uid);

            return StatusCode(StatusCodes.Status201Created, response);
        }
        catch (WalletApiException ex)
        {
            _logger.LogError(ex, "Wallet service error during purchase initiation with status {StatusCode}: {Message}",
                ex.StatusCode, ex.Message);
            return StatusCode(ex.StatusCode, new { error = "Wallet service error", details = ex.Message });
        }
        catch (InAppPurchaseApiException ex)
        {
            _logger.LogError(ex, "Purchase initiation failed with status {StatusCode}: {Message}",
                ex.StatusCode, ex.Message);
            return StatusCode(ex.StatusCode, new { error = ex.Message });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Unexpected error during purchase initiation");
            return StatusCode(500, new { error = "Internal server error", details = ex.Message });
        }
    }

    /// <summary>
    /// Get Purchase Status
    /// </summary>
    /// <remarks>
    /// Get the status of a purchase context
    /// </remarks>
    [HttpGet("purchases/{purchaseContextId}/status")]
    [ProducesResponseType(typeof(PurchaseStatusResponse), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    [ProducesResponseType(StatusCodes.Status401Unauthorized)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType(StatusCodes.Status422UnprocessableEntity)]
    [ProducesResponseType(StatusCodes.Status500InternalServerError)]
    public async Task<IActionResult> GetPurchaseStatus(int purchaseContextId)
    {
        try
        {
            if (CurrentUser == null)
            {
                _logger.LogWarning("GetPurchaseStatus called without authenticated user");
                return Unauthorized(new { error = "Authentication required" });
            }

            _logger.LogInformation("Getting purchase status for context ID {PurchaseContextId} requested by user {UserId}",
                purchaseContextId, CurrentUser.Uid);

            var response = await _inAppPurchaseClient.Get_purchase_statusAsync(purchaseContextId);

            _logger.LogInformation("Successfully retrieved purchase status for context ID {PurchaseContextId}, status: {Status}",
                purchaseContextId, response.Status);

            return Ok(response);
        }
        catch (InAppPurchaseApiException ex)
        {
            _logger.LogError(ex, "Failed to get purchase status for context ID {PurchaseContextId} with status {StatusCode}: {Message}",
                purchaseContextId, ex.StatusCode, ex.Message);
            return StatusCode(ex.StatusCode, new { error = ex.Message });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Unexpected error getting purchase status for context ID {PurchaseContextId}",
                purchaseContextId);
            return StatusCode(500, new { error = "Internal server error", details = ex.Message });
        }
    }

    /// <summary>
    /// Health Check
    /// </summary>
    /// <remarks>
    /// Health check endpoint for the in-app purchase service
    /// </remarks>
    [HttpGet("health")]
    [ProducesResponseType(typeof(object), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status500InternalServerError)]
    public async Task<IActionResult> HealthCheck()
    {
        try
        {
            var response = await _inAppPurchaseClient.Health_checkAsync();
            return Ok(response);
        }
        catch (InAppPurchaseApiException ex)
        {
            _logger.LogError(ex, "Health check failed with status {StatusCode}: {Message}",
                ex.StatusCode, ex.Message);
            return StatusCode(ex.StatusCode, new { error = ex.Message });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Unexpected error during health check");
            return StatusCode(500, new { error = "Internal server error", details = ex.Message });
        }
    }
}

