using System.Text.Json.Serialization;

namespace ThakiiBackend.Api.Models;

/// <summary>
/// Webhook payload received after a successful external payment.
/// Only the gateway payment ID is required — all other data (user, credits,
/// amount) is verified server-side by calling the unified payment gateway.
/// </summary>
public class UnifiedPaymentGatewayWebhookRequest
{
    /// <summary>
    /// The payment ID returned by the unified payment gateway.
    /// The backend verifies the payment status and extracts trusted metadata
    /// (user_id, credit_amount, price) directly from the gateway.
    /// </summary>
    [JsonPropertyName("payment_id")]
    public string? PaymentId { get; set; }
}

