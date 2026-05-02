namespace ThakiiBackend.Api.Services;

/// <summary>
/// Configuration for which unified payment gateways are enabled in this app
/// and how they should be presented (e.g. logo URL).
/// </summary>
public class UnifiedPaymentGatewayOptions
{
    /// <summary>
    /// Gateways available in this application (subset of what the unified service supports).
    /// </summary>
    public List<UnifiedPaymentGatewayDefinition> Gateways { get; set; } = new();
}

public class UnifiedPaymentGatewayDefinition
{
    /// <summary>
    /// Gateway identifier (must match the unified service gateway name, e.g. "myfatoorah").
    /// </summary>
    public string Name { get; set; } = string.Empty;

    /// <summary>
    /// Logo URL or path to use in the UI for this gateway.
    /// </summary>
    public string LogoUrl { get; set; } = string.Empty;

    /// <summary>
    /// Whether this gateway is enabled and should be exposed by this API.
    /// </summary>
    public bool Enabled { get; set; } = true;
}

