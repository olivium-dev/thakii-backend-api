using System.Text.Json.Serialization;

namespace ThakiiBackend.Api.DTO;

/// <summary>
/// Request for the Apple IAP webhook.
/// Use user.holder_id from the auth/login response as UserId (GUID), not the Firebase uid.
/// This DTO is mapped from the gateway's camelCase JSON payload.
/// </summary>
public class AppleIAPWebhookRequest
{
    /// <summary>
    /// Wallet holder ID (GUID). Use the holder_id returned in the auth/login user object.
    /// </summary>
    [JsonPropertyName("userId")]
    public string UserId { get; set; } = string.Empty;

    [JsonPropertyName("creditAmount")]
    public int CreditAmount { get; set; }

    [JsonPropertyName("price")]
    public decimal Price { get; set; }
}

