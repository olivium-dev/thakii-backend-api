# Thakii Backend API (.NET 8)

ASP.NET Core port of the Thakii Lecture2PDF Python/Flask backend. API contract matches the Python version for zero-breaking-change migration.

## Prerequisites

- .NET 8 SDK
- PostgreSQL (same schema as Python version – run `thakii-backend-api/scripts/setup_postgres.sql`)
- AWS S3 bucket and credentials

## Configuration

Set environment variables (or use `appsettings.json`):

- `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`
- `AWS_DEFAULT_REGION`, `S3_BUCKET_NAME`, AWS credentials (or default credential chain)
- `CUSTOM_TOKEN_SECRET` (optional, default in appsettings)
- `ALLOWED_ORIGINS` (comma-separated, e.g. `http://localhost:3000,https://app.example.com`)

## Run

```bash
cd ThakiiBackend.Api
dotnet run
```

API runs at `http://localhost:5000` by default. Swagger UI: `http://localhost:5000/swagger`.

## Implemented Endpoints

| Route | Method | Status |
|-------|--------|--------|
| `/health` | GET | ✅ |
| `/auth/login` | POST | ✅ |
| `/auth/user` | GET | ✅ |
| `/upload` | POST | ✅ |
| `/list` | GET | ✅ |
| `/status/{videoId}` | GET | ✅ |
| `/download/{videoId}` | GET | ✅ |
| `/cancel/{videoId}` | POST | ✅ |
| `/admin/videos` | GET | ✅ |
| `/admin/videos/{videoId}` | DELETE | ✅ |
| `/admin/stats` | GET | ✅ |

## TODO (to fully match Python)

- `/auth/exchange-token`
- `/test-upload`, `/upload-chunk`, `/assemble-file`
- Admin: test-notification, servers, admins, email
- Worker API, internal task-update
- Batch import, import-url

## Database

Uses the same PostgreSQL schema and `cancel_video_task` stored procedure as the Python app. Run `scripts/setup_postgres.sql` and migration scripts from the Python project.
