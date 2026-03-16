using System.Threading.RateLimiting;
using Microsoft.AspNetCore.Http.Features;
using Microsoft.AspNetCore.RateLimiting;
using ThakiiBackend.Api.Services;
using ThakiiBackend.Api.Middleware;
using ThakiiBackend.Api.Middleware.SocketIo;
using ThakiiBackend.Api.Hubs;
using thakii.service.ServiceWallet;
using thakii.service.ServiceCatalog;
using thakii.service.ServiceInAppPurchase;
using saawt.service.ServiceUnifiedPayment;

var builder = WebApplication.CreateBuilder(args);

// Listen on the same port as the old Python backend (5001) so the existing Nginx/proxy config keeps working
builder.WebHost.UseUrls("http://0.0.0.0:5001");

// Kestrel: allow unlimited request body size (null = no limit)
builder.WebHost.ConfigureKestrel(options =>
{
    options.Limits.MaxRequestBodySize = null;
});

// In-memory cache (used for opaque checkout session codes)
builder.Services.AddMemoryCache();

// Rate limiting — per-IP sliding-window limits to stop brute-force and flooding
builder.Services.AddRateLimiter(o =>
{
    o.RejectionStatusCode = 429;

    // Checkout sessions: max 10 creations/minute per IP
    o.AddSlidingWindowLimiter("checkout", cfg =>
    {
        cfg.Window              = TimeSpan.FromMinutes(1);
        cfg.SegmentsPerWindow   = 4;
        cfg.PermitLimit         = 10;
        cfg.QueueLimit          = 0;
        cfg.QueueProcessingOrder = QueueProcessingOrder.OldestFirst;
    });

    // Payment creation: max 20/minute per IP
    o.AddSlidingWindowLimiter("payments", cfg =>
    {
        cfg.Window              = TimeSpan.FromMinutes(1);
        cfg.SegmentsPerWindow   = 4;
        cfg.PermitLimit         = 20;
        cfg.QueueLimit          = 0;
        cfg.QueueProcessingOrder = QueueProcessingOrder.OldestFirst;
    });
});

// Services
builder.Services.AddSingleton<IPostgresDbService, PostgresDbService>();
builder.Services.AddSingleton<IS3StorageService, S3StorageService>();
builder.Services.AddSingleton<ICustomTokenService, CustomTokenService>();
builder.Services.AddSingleton<IVideoPricingService, VideoPricingService>();
builder.Services.AddSingleton<IVideoCatalogService, VideoCatalogService>();
builder.Services.AddSingleton<IVideoCreditRefundService, VideoCreditRefundService>();
builder.Services.AddSingleton<IRemoteVideoDurationService, RemoteVideoDurationService>();

// New services for missing endpoints
builder.Services.AddSingleton<IServerManagerService, ServerManagerService>();
builder.Services.AddSingleton<IAdminManagerService, AdminManagerService>();
builder.Services.AddSingleton<IEmailNotificationService, EmailNotificationService>();
builder.Services.AddSingleton<IPushNotificationService, PushNotificationService>();
builder.Services.AddSingleton<IWorkerManagerService, WorkerManagerService>();
builder.Services.AddSingleton<IBatchImportService, BatchImportService>();
builder.Services.AddSingleton<ITaskUpdateHubService, TaskUpdateHubService>();

builder.Services.AddSingleton<SocketIoServer>();
builder.Services.AddSignalR();

// Allow unlimited request body size for uploads (rely on external limits / infra)
builder.Services.Configure<FormOptions>(options =>
{
    options.MultipartBodyLengthLimit = long.MaxValue;
});

// HttpContextAccessor + CorrelationIdHandler (forwards X-Correlation-ID to downstream services)
builder.Services.AddHttpContextAccessor();
builder.Services.AddTransient<CorrelationIdHandler>();

// HttpClientFactory (used by services for external calls)
builder.Services.AddHttpClient();

// Wallet service client
builder.Services.AddHttpClient<ServiceWalletClient>()
    .AddTypedClient((httpClient, sp) =>
    {
        var config = sp.GetRequiredService<IConfiguration>();
        var baseUrl = config["WalletService:BaseUrl"] ?? Environment.GetEnvironmentVariable("WALLET_SERVICE_URL") ?? "https://localhost:7001/";
        return new ServiceWalletClient(baseUrl, httpClient);
    });

// Catalog service client
builder.Services.AddHttpClient<ServiceCatalogClient>()
    .AddTypedClient((httpClient, sp) =>
    {
        var config = sp.GetRequiredService<IConfiguration>();
        var baseUrl = config["CatalogService:BaseUrl"] ?? Environment.GetEnvironmentVariable("CATALOG_SERVICE_URL") ?? "https://localhost:7002/";
        return new ServiceCatalogClient(baseUrl, httpClient);
    });

// In-app purchase service client
builder.Services.AddHttpClient<ServiceInAppPurchaseClient>()
    .AddTypedClient((httpClient, sp) =>
    {
        var config = sp.GetRequiredService<IConfiguration>();
        var baseUrl = config["ServiceInAppPurchase:BaseUrl"]
                      ?? Environment.GetEnvironmentVariable("IN_APP_PURCHASE_SERVICE_URL")
                      ?? "https://localhost:7003/";
        return new ServiceInAppPurchaseClient(baseUrl, httpClient);
    });

// Unified payment gateway client (unified payment microservice)
// Attaches UNIFIED_PAYMENT_GATEWAY_API_KEY so the gateway's ApiKeyPlug accepts the request.
// Also forwards X-Correlation-ID via CorrelationIdHandler for end-to-end tracing.
builder.Services.AddHttpClient<ServiceUnifiedPaymentGatewayClient>()
    .AddHttpMessageHandler<CorrelationIdHandler>()
    .AddTypedClient((httpClient, sp) =>
    {
        var config = sp.GetRequiredService<IConfiguration>();
        var baseUrl = config["UnifiedPaymentGatewayApi:BaseUrl"] ?? "http://localhost:4000";
        var apiKey = Environment.GetEnvironmentVariable("UNIFIED_PAYMENT_GATEWAY_API_KEY")
                     ?? config["UnifiedPaymentGatewayApi:ApiKey"];
        if (!string.IsNullOrEmpty(apiKey))
            httpClient.DefaultRequestHeaders.Authorization =
                new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", apiKey);
        return new ServiceUnifiedPaymentGatewayClient(httpClient, baseUrl);
    });

// Dedicated HttpClient for raw webhook passthrough.
// Webhooks MUST NOT be deserialized/re-serialized — the HMAC signature covers the exact bytes.
// This client sends no Authorization header; the gateway authenticates webhooks via HMAC only.
// Correlation ID is still forwarded so webhook traces can be linked to the original request.
builder.Services.AddHttpClient("UnifiedPaymentGatewayWebhook", (sp, client) =>
{
    var config = sp.GetRequiredService<IConfiguration>();
    var baseUrl = (config["UnifiedPaymentGatewayApi:BaseUrl"] ?? "http://localhost:4000").TrimEnd('/');
    client.BaseAddress = new Uri(baseUrl + "/");
    client.Timeout = TimeSpan.FromSeconds(30);
}).AddHttpMessageHandler<CorrelationIdHandler>();

// Unified payment gateway configuration (enabled gateways, logos, etc.)
builder.Services.Configure<UnifiedPaymentGatewayOptions>(
    builder.Configuration.GetSection("UnifiedPaymentGateway"));

// Controllers - use snake_case to match Python API contract.
// PropertyNameCaseInsensitive allows "KWD" to match the enum member regardless of case.
// JsonStringEnumConverter(SnakeCaseLower) serialises enums as lowercase strings ("captured",
// "kwd") and deserialises any casing ("KWD", "kwd") of those values.
builder.Services.AddControllers()
    .AddJsonOptions(o =>
    {
        o.JsonSerializerOptions.PropertyNamingPolicy       = System.Text.Json.JsonNamingPolicy.SnakeCaseLower;
        o.JsonSerializerOptions.PropertyNameCaseInsensitive = true;
        o.JsonSerializerOptions.Converters.Add(
            new System.Text.Json.Serialization.JsonStringEnumConverter(
                System.Text.Json.JsonNamingPolicy.SnakeCaseLower));
    });

// CORS
var allowedOrigins = Environment.GetEnvironmentVariable("ALLOWED_ORIGINS");
if (!string.IsNullOrEmpty(allowedOrigins))
{
    // Production: explicit origin list + credentials (for cookie-based auth if ever added)
    var origins = allowedOrigins.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
    builder.Services.AddCors(o => o.AddDefaultPolicy(p =>
        p.WithOrigins(origins).AllowAnyMethod().AllowAnyHeader().AllowCredentials()));
}
else if (builder.Environment.IsDevelopment())
{
    // Development: allow everything — payment-web, thakii-frontend, ngrok tunnels, etc.
    // AllowAnyOrigin() sets Access-Control-Allow-Origin: * which all browsers accept without issue.
    // Note: AllowAnyOrigin() cannot be combined with AllowCredentials(); credentials are not
    // needed here since the payment-web does not send cookies.
    builder.Services.AddCors(o => o.AddDefaultPolicy(p =>
        p.AllowAnyOrigin().AllowAnyMethod().AllowAnyHeader()));
}
else
{
    // Non-development fallback: restrict to known local origins
    var devOrigins = new[] { "http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:3000", "http://127.0.0.1:5173" };
    builder.Services.AddCors(o => o.AddDefaultPolicy(p =>
        p.WithOrigins(devOrigins).AllowAnyMethod().AllowAnyHeader().AllowCredentials()));
}

// Swagger
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen();

var app = builder.Build();

// Enforce HTTPS in non-development environments
if (!app.Environment.IsDevelopment())
{
    app.UseHsts();
    app.UseHttpsRedirection();
}

app.UseCorrelationId();
app.UseCors();
app.UseRateLimiter();
app.UseMiddleware<SocketIoMiddleware>();
app.UseAuthMiddleware();
app.MapControllers();
app.MapHub<TaskUpdateHub>("/hubs/task-update");

// Initialize pricing assets (like Rahmah chat packages)
using (var scope = app.Services.CreateScope())
{
    var videoCatalog = scope.ServiceProvider.GetRequiredService<IVideoCatalogService>();
    await videoCatalog.EnsurePricingAssetsAsync();
}

// Ensure super admins exist
using (var scope = app.Services.CreateScope())
{
    var adminManager = scope.ServiceProvider.GetRequiredService<IAdminManagerService>();
    adminManager.EnsureSuperAdminsExist();
}

if (app.Environment.IsDevelopment())
{
    app.UseSwagger();
    app.UseSwaggerUI();
}

app.Run();
