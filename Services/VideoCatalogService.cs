using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using thakii.service.ServiceCatalog;

namespace ThakiiBackend.Api.Services;

public interface IVideoCatalogService
{
    /// <summary>
    /// Ensure pricing asset(s) exist in catalog based on configuration.
    /// Called on startup to sync pricing with Catalog.
    /// </summary>
    Task EnsurePricingAssetsAsync();

    /// <summary>
    /// Returns all catalog items representing Thakii pricing assets.
    /// </summary>
    Task<IReadOnlyList<ItemResponse>> GetAllPricingAssetsAsync();
}

public class VideoCatalogService : IVideoCatalogService
{
    private readonly IConfiguration _configuration;
    private readonly ServiceCatalogClient _catalogClient;
    private readonly ILogger<VideoCatalogService> _logger;

    private Guid? _cachedCategoryGuid;
    private readonly string _categoryName;
    private readonly string _itemType;

    public VideoCatalogService(
        IConfiguration configuration,
        ServiceCatalogClient catalogClient,
        ILogger<VideoCatalogService> logger)
    {
        _configuration = configuration;
        _catalogClient = catalogClient;
        _logger = logger;

        // These describe where pricing assets live in Catalog
        _categoryName = _configuration["VideoCatalog:CategoryName"] ?? "thakii-video-assets";
        _itemType = _configuration["VideoCatalog:ItemType"] ?? "thakii-video-pricing";
    }

    /// <summary>
    /// Ensure a single pricing asset exists/updated using VideoPricing:MinutesPerCredit.
    /// </summary>
    public async Task EnsurePricingAssetsAsync()
    {
        var categoryGuid = await EnsureCategoryExistsAsync();

        var minutesPerCreditConfig = _configuration["VideoPricing:MinutesPerCredit"];
        if (!int.TryParse(minutesPerCreditConfig, out var minutesPerCredit) || minutesPerCredit <= 0)
            minutesPerCredit = 10;

        const string assetName = "thakii-video-default-pricing";

        // Look for existing asset by name (mimic Rahmah ChatPackagesInitializationService)
        var searchRequest = new SearchItemsRequest
        {
            Query = assetName,
            PageNumber = 1,
            PageSize = 10
        };

        var searchResult = await _catalogClient.SearchAsync(searchRequest);
        var existingItem = searchResult.Items?
            .FirstOrDefault(i =>
                string.Equals(i.Name, assetName, StringComparison.OrdinalIgnoreCase));

        var additionalParams = new Dictionary<string, string>
        {
            ["minutes_per_credit"] = minutesPerCredit.ToString(),
            ["credits_per_unit"] = "1"
        };

        if (existingItem != null)
        {
            _logger.LogInformation("Updating pricing asset '{AssetName}' (ItemGuid={ItemGuid})", assetName, existingItem.Guid);

            var updateRequest = new UpdateItemRequest
            {
                Guid = existingItem.Guid,
                Parent = categoryGuid,
                Type = _itemType,
                Tags = new List<string> { "thakii", "pricing", "video" },
                Details = new[]
                {
                    new ItemDetailsRequest
                    {
                        Name = assetName,
                        Description = $"Thakii video pricing: {minutesPerCredit} minutes per 1 credit",
                        Language = "en"
                    }
                },
                AdditionalParams = additionalParams,
                Categories = new List<string> { categoryGuid.ToString() }
            };

            await _catalogClient.ItemPUTAsync(updateRequest);
            return;
        }

        _logger.LogInformation("Creating pricing asset '{AssetName}' for Thakii video", assetName);

        var createRequest = new CreateItemRequest
        {
            Parent = categoryGuid,
            Type = _itemType,
            Tags = new List<string> { "thakii", "pricing", "video" },
            Details = new[]
            {
                new ItemDetailsRequest
                {
                    Name = assetName,
                    Description = $"Thakii video pricing: {minutesPerCredit} minutes per 1 credit",
                    Language = "en"
                }
            },
            AdditionalParams = additionalParams,
            Categories = new List<string> { categoryGuid.ToString() }
        };

        await _catalogClient.ItemPOSTAsync(createRequest);
    }

    public async Task<IReadOnlyList<ItemResponse>> GetAllPricingAssetsAsync()
    {
        await EnsureCategoryExistsAsync();

        var searchRequest = new SearchItemsRequest
        {
            Query = string.Empty,
            PageNumber = 1,
            PageSize = 200
        };

        var result = await _catalogClient.SearchAsync(searchRequest);
        var items = result.Items ?? Array.Empty<ItemResponse>();

        // Filter locally by type to ensure we only return our pricing assets
        return items
            .Where(i => string.Equals(i.Type, _itemType, StringComparison.OrdinalIgnoreCase))
            .ToList();
    }

    private async Task<Guid> EnsureCategoryExistsAsync()
    {
        if (_cachedCategoryGuid.HasValue)
            return _cachedCategoryGuid.Value;

        try
        {
            var allCategories = await _catalogClient.AllAsync(50, 1);
            var existing = allCategories.Categories?
                .FirstOrDefault(c => string.Equals(c.Name, _categoryName, StringComparison.OrdinalIgnoreCase));

            if (existing != null)
            {
                _cachedCategoryGuid = existing.Guid;
                _logger.LogInformation("Video catalog category '{CategoryName}' already exists with GUID {Guid}", _categoryName, existing.Guid);
                return existing.Guid;
            }

            _logger.LogInformation("Video catalog category '{CategoryName}' not found. Creating...", _categoryName);

            var createRequest = new CreateCategoryRequest
            {
                Details = new[]
                {
                    new CategoryDetailsRequest
                    {
                        Name = _categoryName,
                        Language = "en"
                    }
                }
            };

            var result = await _catalogClient.CategoryPOSTAsync(createRequest);
            _cachedCategoryGuid = result.Guid;

            _logger.LogInformation("Created video catalog category '{CategoryName}' with GUID {Guid}", _categoryName, result.Guid);
            return result.Guid;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error ensuring video catalog category '{CategoryName}' exists", _categoryName);
            throw;
        }
    }
}

