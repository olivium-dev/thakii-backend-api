using Microsoft.Extensions.Configuration;

namespace ThakiiBackend.Api.Services;

public interface IVideoPricingService
{
    /// <summary>
    /// Calculates how many credits are required for the given number of minutes.
    /// Example: if MinutesPerCredit = 10, then:
    ///  - 0..10 minutes => 1 credit
    ///  - 10.01..20 minutes => 2 credits, etc.
    /// </summary>
    /// <param name="totalMinutes">Total minutes of video usage.</param>
    /// <returns>Credits to charge as a decimal (no ceiling).</returns>
    decimal CalculateCreditsForMinutes(double totalMinutes);

    /// <summary>
    /// Returns the configured MinutesPerCredit value.
    /// </summary>
    int GetMinutesPerCredit();
}

public class VideoPricingService : IVideoPricingService
{
    private readonly int _minutesPerCredit;

    public VideoPricingService(IConfiguration configuration)
    {
        // Default to 10 if not configured, matching the requirement "10 min = 1 credit"
        var configured = configuration["VideoPricing:MinutesPerCredit"];
        if (!int.TryParse(configured, out _minutesPerCredit) || _minutesPerCredit <= 0)
        {
            _minutesPerCredit = 10;
        }
    }

    public decimal CalculateCreditsForMinutes(double totalMinutes)
    {
        if (totalMinutes <= 0)
            return 0m;

        // Example: MinutesPerCredit = 10, totalMinutes = 5 => 0.5 credits
        var raw = (decimal)totalMinutes / _minutesPerCredit;
        return raw;
    }

    public int GetMinutesPerCredit() => _minutesPerCredit;
}

