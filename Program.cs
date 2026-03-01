using Microsoft.AspNetCore.Http.Features;
using ThakiiBackend.Api.Services;
using ThakiiBackend.Api.Middleware;
using ThakiiBackend.Api.Hubs;
using thakii.service.ServiceWallet;
using thakii.service.ServiceCatalog;

var builder = WebApplication.CreateBuilder(args);

// Kestrel: allow unlimited request body size (null = no limit)
builder.WebHost.ConfigureKestrel(options =>
{
    options.Limits.MaxRequestBodySize = null;
});

// Services
builder.Services.AddSingleton<IPostgresDbService, PostgresDbService>();
builder.Services.AddSingleton<IS3StorageService, S3StorageService>();
builder.Services.AddSingleton<ICustomTokenService, CustomTokenService>();
builder.Services.AddSingleton<IVideoPricingService, VideoPricingService>();
builder.Services.AddSingleton<IVideoCatalogService, VideoCatalogService>();

// New services for missing endpoints
builder.Services.AddSingleton<IServerManagerService, ServerManagerService>();
builder.Services.AddSingleton<IAdminManagerService, AdminManagerService>();
builder.Services.AddSingleton<IEmailNotificationService, EmailNotificationService>();
builder.Services.AddSingleton<IPushNotificationService, PushNotificationService>();
builder.Services.AddSingleton<IWorkerManagerService, WorkerManagerService>();
builder.Services.AddSingleton<IBatchImportService, BatchImportService>();
builder.Services.AddSingleton<ITaskUpdateHubService, TaskUpdateHubService>();

builder.Services.AddSignalR();

// Allow unlimited request body size for uploads (rely on external limits / infra)
builder.Services.Configure<FormOptions>(options =>
{
    options.MultipartBodyLengthLimit = long.MaxValue;
});

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

// Controllers - use snake_case to match Python API contract
builder.Services.AddControllers()
    .AddJsonOptions(o => o.JsonSerializerOptions.PropertyNamingPolicy = System.Text.Json.JsonNamingPolicy.SnakeCaseLower);

// CORS - AllowCredentials requires specific origins, not wildcard
var allowedOrigins = Environment.GetEnvironmentVariable("ALLOWED_ORIGINS");
if (!string.IsNullOrEmpty(allowedOrigins))
{
    var origins = allowedOrigins.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
    builder.Services.AddCors(o => o.AddDefaultPolicy(p => p.WithOrigins(origins).AllowAnyMethod().AllowAnyHeader().AllowCredentials()));
}
else
{
    // Dev: allow common localhost origins (wildcard + credentials not allowed in CORS)
    var devOrigins = new[] { "http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:3000", "http://127.0.0.1:5173", "http://localhost:5000" };
    builder.Services.AddCors(o => o.AddDefaultPolicy(p => p.WithOrigins(devOrigins).AllowAnyMethod().AllowAnyHeader().AllowCredentials()));
}

// Swagger
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen();

var app = builder.Build();

app.UseCors();
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
