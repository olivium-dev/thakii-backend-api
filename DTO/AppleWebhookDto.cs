using System.Text.Json.Serialization;

namespace ThakiiBackend.Api.DTO;

public sealed class AppleWebhookDto
{
    [JsonPropertyName("signedPayload")]
    public string SignedPayload { get; set; } = string.Empty;
}

