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
    /// <returns>Credits to charge (at least 1 if totalMinutes &gt; 0).</returns>
    int CalculateCreditsForMinutes(double totalMinutes);

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

    public int CalculateCreditsForMinutes(double totalMinutes)
    {
        if (totalMinutes <= 0)
            return 0;

        var raw = totalMinutes / _minutesPerCredit;
        var credits = (int)Math.Ceiling(raw);
        return credits < 1 ? 1 : credits;
    }

    public int GetMinutesPerCredit() => _minutesPerCredit;
}

