using System.Text;
using System.Text.Json;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.RateLimiting;
using Microsoft.Extensions.Options;
using Newtonsoft.Json;
using saawt.service.ServiceUnifiedPayment;
using ThakiiBackend.Api.Services;
using UnifiedPaymentApiException = saawt.service.ServiceUnifiedPayment.ApiException;

namespace ThakiiBackend.Api.Controllers;

[ApiController]
[Route("api/UnifiedPaymentGateway")]
public class UnifiedPaymentGatewayController : ControllerBase
{
    private readonly ServiceUnifiedPaymentGatewayClient _client;
    private readonly IHttpClientFactory _httpClientFactory;
    private readonly string _gatewayBaseUrl;
    private readonly Dictionary<string, UnifiedPaymentGatewayDefinition> _enabledGateways;

    public UnifiedPaymentGatewayController(
        ServiceUnifiedPaymentGatewayClient client,
        IHttpClientFactory httpClientFactory,
        IConfiguration config,
        IOptions<UnifiedPaymentGatewayOptions> options)
    {
        _client = client;
        _httpClientFactory = httpClientFactory;
        _gatewayBaseUrl = (config["UnifiedPaymentGatewayApi:BaseUrl"] ?? "http://localhost:4000").TrimEnd('/');
        _enabledGateways = options.Value.Gateways
            .Where(g => g.Enabled && !string.IsNullOrWhiteSpace(g.Name))
            .ToDictionary(g => g.Name, g => g, StringComparer.OrdinalIgnoreCase);
    }

    // ----- Gateways -----
    [HttpGet("v1/gateways")]
    [ProducesResponseType(typeof(GatewayListResponse), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status502BadGateway)]
    public async Task<IActionResult> GetGateways(CancellationToken cancellationToken)
    {
        try
        {
            var response = await _client.GatewaysAsync(cancellationToken);

            // Only expose gateways that are enabled in configuration and enrich with logo URLs.
            var gateways = response.Data
                .Where(g => g != null && IsGatewayEnabled(g.Name))
                .Select(g =>
                {
                    var config = _enabledGateways[g.Name];
                    return new
                    {
                        name = g.Name,
                        paymentMethods = g.Payment_methods,
                        currencies = g.Currencies,
                        logoUrl = config.LogoUrl
                    };
                })
                .ToList();

            return Ok(new { data = gateways });
        }
        catch (UnifiedPaymentApiException ex)
        {
            return StatusCode(ex.StatusCode, ex.Message);
        }
        catch (Exception ex)
        {
            return StatusCode(500, "Internal server error: " + ex.Message);
        }
    }

    // ----- Payments -----
    [HttpPost("v1/payments")]
    [EnableRateLimiting("payments")]
    [ProducesResponseType(typeof(PaymentResponse), StatusCodes.Status201Created)]
    [ProducesResponseType(StatusCodes.Status422UnprocessableEntity)]
    [ProducesResponseType(StatusCodes.Status502BadGateway)]
    public async Task<IActionResult> CreatePayment([FromBody] CreatePaymentRequest request, CancellationToken cancellationToken)
    {
        try
        {
            if (!IsGatewayEnabled(request.Gateway))
            {
                return BadRequest($"Gateway '{request.Gateway}' is not enabled.");
            }

            // ASP.NET Core deserializes `object` properties as System.Text.Json.JsonElement,
            // but the NSwag client re-serializes with Newtonsoft.Json which doesn't understand
            // JsonElement — producing {"ValueKind":1} instead of the actual JSON.
            if (request.Metadata is JsonElement metadataElement)
            {
                request.Metadata = JsonConvert.DeserializeObject(metadataElement.GetRawText());
            }

            var response = await _client.CreatePaymentAsync(request, cancellationToken);
            return StatusCode(201, response);
        }
        catch (UnifiedPaymentApiException ex)
        {
            return StatusCode(ex.StatusCode, ex.Message);
        }
        catch (Exception ex)
        {
            return StatusCode(500, "Internal server error: " + ex.Message);
        }
    }

    [HttpGet("v1/payments/{id}")]
    [ProducesResponseType(typeof(PaymentDetailResponse), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType(StatusCodes.Status502BadGateway)]
    public async Task<IActionResult> GetPayment(string id, CancellationToken cancellationToken)
    {
        try
        {
            var response = await _client.GetPaymentAsync(id, cancellationToken);
            var json = JsonConvert.SerializeObject(response, new Newtonsoft.Json.Converters.StringEnumConverter());
            return Content(json, "application/json");
        }
        catch (UnifiedPaymentApiException ex)
        {
            return StatusCode(ex.StatusCode, ex.Message);
        }
        catch (Exception ex)
        {
            return StatusCode(500, "Internal server error: " + ex.Message);
        }
    }

    [HttpPost("v1/payments/{id}/capture")]
    [ProducesResponseType(typeof(PaymentResponse), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType(StatusCodes.Status422UnprocessableEntity)]
    [ProducesResponseType(StatusCodes.Status502BadGateway)]
    public async Task<IActionResult> CapturePayment(string id, [FromBody] CaptureRequest request, CancellationToken cancellationToken)
    {
        try
        {
            var response = await _client.CapturePaymentAsync(id, request, cancellationToken);
            return Ok(response);
        }
        catch (UnifiedPaymentApiException ex)
        {
            return StatusCode(ex.StatusCode, ex.Message);
        }
        catch (Exception ex)
        {
            return StatusCode(500, "Internal server error: " + ex.Message);
        }
    }

    [HttpPost("v1/payments/{id}/release")]
    [ProducesResponseType(typeof(PaymentResponse), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType(StatusCodes.Status502BadGateway)]
    public async Task<IActionResult> ReleasePayment(string id, CancellationToken cancellationToken)
    {
        try
        {
            var response = await _client.ReleasePaymentAsync(id, cancellationToken);
            return Ok(response);
        }
        catch (UnifiedPaymentApiException ex)
        {
            return StatusCode(ex.StatusCode, ex.Message);
        }
        catch (Exception ex)
        {
            return StatusCode(500, "Internal server error: " + ex.Message);
        }
    }

    [HttpPost("v1/payments/{id}/refund")]
    [ProducesResponseType(typeof(RefundResponse), StatusCodes.Status201Created)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType(StatusCodes.Status502BadGateway)]
    public async Task<IActionResult> RefundPayment(string id, [FromBody] RefundRequest request, CancellationToken cancellationToken)
    {
        try
        {
            var response = await _client.RefundPaymentAsync(id, request, cancellationToken);
            return StatusCode(201, response);
        }
        catch (UnifiedPaymentApiException ex)
        {
            return StatusCode(ex.StatusCode, ex.Message);
        }
        catch (Exception ex)
        {
            return StatusCode(500, "Internal server error: " + ex.Message);
        }
    }

    // ----- Sessions -----
    [HttpPost("v1/sessions")]
    [ProducesResponseType(typeof(SessionResponse), StatusCodes.Status201Created)]
    [ProducesResponseType(StatusCodes.Status422UnprocessableEntity)]
    [ProducesResponseType(StatusCodes.Status502BadGateway)]
    public async Task<IActionResult> CreateSession([FromBody] CreateSessionRequest request, CancellationToken cancellationToken)
    {
        try
        {
            if (!IsGatewayEnabled(request.Gateway))
            {
                return BadRequest($"Gateway '{request.Gateway}' is not enabled.");
            }

            var response = await _client.CreateSessionAsync(request, cancellationToken);
            return StatusCode(201, response);
        }
        catch (UnifiedPaymentApiException ex)
        {
            return StatusCode(ex.StatusCode, ex.Message);
        }
        catch (Exception ex)
        {
            return StatusCode(500, "Internal server error: " + ex.Message);
        }
    }

    [HttpGet("v1/sessions/{id}")]
    [ProducesResponseType(typeof(SessionResponse), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType(StatusCodes.Status502BadGateway)]
    public async Task<IActionResult> GetSession(string id, CancellationToken cancellationToken)
    {
        try
        {
            var response = await _client.GetSessionAsync(id, cancellationToken);
            return Ok(response);
        }
        catch (UnifiedPaymentApiException ex)
        {
            return StatusCode(ex.StatusCode, ex.Message);
        }
        catch (Exception ex)
        {
            return StatusCode(500, "Internal server error: " + ex.Message);
        }
    }

    // ----- Customers -----
    [HttpGet("v1/customers/{reference}")]
    [ProducesResponseType(typeof(CustomerResponse), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType(StatusCodes.Status502BadGateway)]
    public async Task<IActionResult> GetCustomer(string reference, CancellationToken cancellationToken)
    {
        try
        {
            var response = await _client.GetCustomerAsync(reference, cancellationToken);
            return Ok(response);
        }
        catch (UnifiedPaymentApiException ex)
        {
            return StatusCode(ex.StatusCode, ex.Message);
        }
        catch (Exception ex)
        {
            return StatusCode(500, "Internal server error: " + ex.Message);
        }
    }

    // ----- Recurring -----
    [HttpPost("v1/recurring")]
    [ProducesResponseType(typeof(RecurringResponse), StatusCodes.Status201Created)]
    [ProducesResponseType(StatusCodes.Status422UnprocessableEntity)]
    [ProducesResponseType(StatusCodes.Status502BadGateway)]
    public async Task<IActionResult> CreateRecurring([FromBody] CreateRecurringRequest request, CancellationToken cancellationToken)
    {
        try
        {
            if (!IsGatewayEnabled(request.Gateway))
            {
                return BadRequest($"Gateway '{request.Gateway}' is not enabled.");
            }

            var response = await _client.CreateRecurringAsync(request, cancellationToken);
            return StatusCode(201, response);
        }
        catch (UnifiedPaymentApiException ex)
        {
            return StatusCode(ex.StatusCode, ex.Message);
        }
        catch (Exception ex)
        {
            return StatusCode(500, "Internal server error: " + ex.Message);
        }
    }

    [HttpGet("v1/recurring/{id}")]
    [ProducesResponseType(typeof(RecurringResponse), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType(StatusCodes.Status502BadGateway)]
    public async Task<IActionResult> GetRecurring(string id, CancellationToken cancellationToken)
    {
        try
        {
            var response = await _client.GetRecurringAsync(id, cancellationToken);
            return Ok(response);
        }
        catch (UnifiedPaymentApiException ex)
        {
            return StatusCode(ex.StatusCode, ex.Message);
        }
        catch (Exception ex)
        {
            return StatusCode(500, "Internal server error: " + ex.Message);
        }
    }

    [HttpPost("v1/recurring/{id}/cancel")]
    [ProducesResponseType(typeof(RecurringResponse), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType(StatusCodes.Status502BadGateway)]
    public async Task<IActionResult> CancelRecurring(string id, CancellationToken cancellationToken)
    {
        try
        {
            var response = await _client.CancelRecurringAsync(id, cancellationToken);
            return Ok(response);
        }
        catch (UnifiedPaymentApiException ex)
        {
            return StatusCode(ex.StatusCode, ex.Message);
        }
        catch (Exception ex)
        {
            return StatusCode(500, "Internal server error: " + ex.Message);
        }
    }

    [HttpPost("v1/recurring/{id}/resume")]
    [ProducesResponseType(typeof(RecurringResponse), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType(StatusCodes.Status502BadGateway)]
    public async Task<IActionResult> ResumeRecurring(string id, CancellationToken cancellationToken)
    {
        try
        {
            var response = await _client.ResumeRecurringAsync(id, cancellationToken);
            return Ok(response);
        }
        catch (UnifiedPaymentApiException ex)
        {
            return StatusCode(ex.StatusCode, ex.Message);
        }
        catch (Exception ex)
        {
            return StatusCode(500, "Internal server error: " + ex.Message);
        }
    }

    // ----- Webhooks -----
    // Raw passthrough — the body is forwarded byte-for-byte to the unified gateway so that
    // the HMAC-SHA256 signature computed by MyFatoorah (or any other provider) over the original
    // bytes still matches. Any JSON deserialization + re-serialization would alter whitespace /
    // key ordering and break signature verification.
    [HttpPost("v1/webhooks/{gateway}")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    [ProducesResponseType(StatusCodes.Status401Unauthorized)]
    [ProducesResponseType(StatusCodes.Status502BadGateway)]
    public async Task<IActionResult> Webhook(string gateway, CancellationToken cancellationToken)
    {
        if (!IsGatewayEnabled(gateway))
            return BadRequest(new { error = $"Gateway '{gateway}' is not enabled." });

        // Read the raw body as the original bytes — do NOT bind via [FromBody].
        string rawBody;
        using (var reader = new StreamReader(Request.Body, Encoding.UTF8, leaveOpen: true))
            rawBody = await reader.ReadToEndAsync(cancellationToken);

        var targetUrl = $"{_gatewayBaseUrl}/api/v1/webhooks/{Uri.EscapeDataString(gateway)}";

        using var fwd = new HttpRequestMessage(HttpMethod.Post, targetUrl)
        {
            Content = new StringContent(rawBody, Encoding.UTF8, "application/json")
        };

        // Forward every gateway-specific signature header so the microservice can verify HMAC.
        // Extend this list as new gateways are added.
        string[] signatureHeaders =
        [
            "x-myfatoorah-signature",
            "X-MyFatoorah-Signature",
            "x-signature",
            "X-Signature",
            "x-stripe-signature",
        ];
        foreach (var name in signatureHeaders)
        {
            if (Request.Headers.TryGetValue(name, out var values))
                fwd.Headers.TryAddWithoutValidation(name, (IEnumerable<string?>)values);
        }

        var http = _httpClientFactory.CreateClient("UnifiedPaymentGatewayWebhook");

        try
        {
            using var resp = await http.SendAsync(fwd, cancellationToken);
            var respBody = await resp.Content.ReadAsStringAsync(cancellationToken);
            return StatusCode((int)resp.StatusCode, respBody);
        }
        catch (HttpRequestException ex)
        {
            return StatusCode(502, new { error = "Failed to reach payment gateway.", details = ex.Message });
        }
    }

    private bool IsGatewayEnabled(string? gatewayName)
    {
        if (string.IsNullOrWhiteSpace(gatewayName))
        {
            return false;
        }

        return _enabledGateways.ContainsKey(gatewayName);
    }
}

