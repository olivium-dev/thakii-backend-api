using thakii.service.ServiceWallet;

namespace ThakiiBackend.Api.Services;

public interface IVideoCreditRefundService
{
    /// <summary>
    /// Refunds the credits that were charged for this video (e.g. when worker fails).
    /// Idempotent: no-op if credits_charged is 0 or already refunded.
    /// </summary>
    /// <returns>True if a refund was performed, false if skipped (nothing to refund or already refunded).</returns>
    Task<bool> RefundCreditsForVideoAsync(string videoId, string reason);
}

public class VideoCreditRefundService : IVideoCreditRefundService
{
    private readonly IPostgresDbService _db;
    private readonly ServiceWalletClient _walletClient;
    private readonly ILogger<VideoCreditRefundService> _logger;

    public VideoCreditRefundService(
        IPostgresDbService db,
        ServiceWalletClient walletClient,
        ILogger<VideoCreditRefundService> logger)
    {
        _db = db;
        _walletClient = walletClient;
        _logger = logger;
    }

    private static Guid UidToHolderId(string uid)
    {
        using var md5 = System.Security.Cryptography.MD5.Create();
        var bytes = System.Text.Encoding.UTF8.GetBytes(uid);
        var hash = md5.ComputeHash(bytes);
        return new Guid(hash);
    }

    public async Task<bool> RefundCreditsForVideoAsync(string videoId, string reason)
    {
        var task = await _db.GetVideoTaskAsync(videoId);
        if (task == null)
        {
            _logger.LogWarning("Refund skipped for {VideoId}: task not found", videoId);
            return false;
        }

        var userId = task.GetValueOrDefault("user_id")?.ToString();
        if (string.IsNullOrEmpty(userId))
        {
            _logger.LogWarning("Refund skipped for {VideoId}: no user_id", videoId);
            return false;
        }

        decimal creditsCharged = 0m;
        var chargedObj = task.GetValueOrDefault("credits_charged");
        if (chargedObj != null)
        {
            if (chargedObj is decimal d) creditsCharged = d;
            else if (chargedObj is double dbl) creditsCharged = (decimal)dbl;
            else if (chargedObj is float f) creditsCharged = (decimal)f;
            else if (chargedObj is int i) creditsCharged = i;
            else if (chargedObj is long l) creditsCharged = l;
            else decimal.TryParse(chargedObj.ToString(), out creditsCharged);
        }

        var refundedObj = task.GetValueOrDefault("credits_refunded");
        var alreadyRefunded = refundedObj is true || (refundedObj is bool b && b);

        if (creditsCharged <= 0m || alreadyRefunded)
        {
            _logger.LogInformation("Refund skipped for {VideoId}: credits_charged={Credits}, already_refunded={Refunded}",
                videoId, creditsCharged, alreadyRefunded);
            return false;
        }

        var holderId = UidToHolderId(userId);
        try
        {
            var systemWallet = await _walletClient.SystemWalletAsync();
            var systemCreditWalletId = systemWallet.Wallets?.FirstOrDefault(w => w.Type == "__SYSTEM__")?.WalletId;
            if (systemCreditWalletId == null)
            {
                _logger.LogError("Refund failed for {VideoId}: system wallet not found", videoId);
                return false;
            }

            var holder = await _walletClient.WalletsAsync(holderId);
            if (holder.WalletHolder == null || holder.Wallets == null || !holder.Wallets.Any())
            {
                _logger.LogError("Refund failed for {VideoId}: user wallet not found", videoId);
                return false;
            }

            var userCreditWallet = holder.Wallets.FirstOrDefault(w => w.CurrencyID == 1);
            if (userCreditWallet == null)
            {
                _logger.LogError("Refund failed for {VideoId}: user credit wallet not found", videoId);
                return false;
            }

            var transaction = new TransactionRequest
            {
                ServiceName = "ThakiiVideoService",
                Tag = $"VideoRefund-{videoId}",
                Notes = reason ?? $"Refund for video {videoId} (e.g. worker failed)",
                Transactions = new List<TransactionDetailsRequest>
                {
                    new TransactionDetailsRequest
                    {
                        SourceWalletId = (Guid)systemCreditWalletId,
                        DestinationWalletId = userCreditWallet.WalletId,
                        Amount = (double)creditsCharged
                    }
                }
            };

            var txResult = await _walletClient.InitiateAsync(transaction);
            await _walletClient.ExecuteAsync(txResult.TransactionHeader.TxId);

            await _db.UpdateVideoTaskAsync(videoId, new Dictionary<string, object?>
            {
                ["credits_refunded"] = true,
                ["refund_reason"] = reason ?? "Worker failed"
            });

            _logger.LogInformation("Refunded {Credits} credits for video {VideoId}, user {UserId}. Reason: {Reason}. TxId={TxId}",
                creditsCharged, videoId, userId, reason, txResult.TransactionHeader.TxId);
            return true;
        }
        catch (ApiException ex)
        {
            _logger.LogError(ex, "Wallet API error refunding credits for video {VideoId}", videoId);
            throw;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Unexpected error refunding credits for video {VideoId}", videoId);
            throw;
        }
    }
}
