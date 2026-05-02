using ThakiiBackend.Api.Middleware;

namespace ThakiiBackend.Api.Services;

/// <summary>
/// DelegatingHandler that forwards the X-Correlation-ID from the current
/// HttpContext to every outbound HttpClient request. This lets you trace a
/// single user action across ThakiiBackend → unified_payment_gateway logs.
/// </summary>
public class CorrelationIdHandler : DelegatingHandler
{
    private readonly IHttpContextAccessor _accessor;

    public CorrelationIdHandler(IHttpContextAccessor accessor)
    {
        _accessor = accessor;
    }

    protected override Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request,
        CancellationToken cancellationToken)
    {
        var correlationId = _accessor.HttpContext?.Items[CorrelationIdMiddleware.HeaderName] as string;

        if (!string.IsNullOrEmpty(correlationId))
            request.Headers.TryAddWithoutValidation(CorrelationIdMiddleware.HeaderName, correlationId);

        return base.SendAsync(request, cancellationToken);
    }
}
