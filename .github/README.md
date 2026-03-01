# ThakiiBackend.Api – GitHub Actions

Workflows and the composite action in this folder are set up for the **.NET** backend (ThakiiBackend.Api).

## Configuration

- **`BACKEND_PATH`** (in workflow `env`): Server path where the repo is deployed, e.g. `/home/ec2-user/ThakiiBackend.Api`. Change it if your server uses a different path.
- **`SERVICE_NAME`** (in `deploy.yml`): systemd service name, default `thakii-backend`. Must match the service that runs the .NET app.
- **Secrets**: `THAKII_SSH_PRIVATE_KEY` (and `thakii_ssh_private_key` where used) for SSH via Cloudflare.

## Workflows

| Workflow | Purpose |
|----------|--------|
| **test.yml** | CI: build and test on PR/push (dotnet restore, build, optional DB schema, optional tests). |
| **deploy.yml** | Deploy on push to `main`: git pull, `dotnet publish`, optional SQL migrations, systemd restart, health check. |
| **check-actual-logs.yml**, **check-systemd-log.yml**, **check-specific-video-logs.yml** | Manual: inspect backend logs (file or journalctl). |
| **check-logging-config.yml**, **check-backend-status.yml** | Manual: check logging config and service status. |
| **reset-and-test.yml**, **fix-backend-and-test.yml** | Manual: reset queue and run tests. |
| **enable-worker-api.yml** | Manual: enable Worker API in backend .env. |
| **test-worker-connectivity.yml** | Manual: test worker connectivity (expects script or use curl to `/worker-health`). |
| **setup_thakii03_primary.yml**, **setup-thakii3-worker.yml** | Server/worker setup (paths updated for .NET backend). |
| **update-api-docs.yml.disabled**, **deploy-server-simple.yml.disabled** | Disabled; were for Python/Flask. |

## Server expectations

- Repo cloned at `BACKEND_PATH`.
- `dotnet publish -c Release -o ./publish` run from repo root; systemd runs the app from `./publish` (or your chosen output dir).
- `.env` in `BACKEND_PATH` for overrides (Worker URLs, etc.); systemd service should load it via `EnvironmentFile=`.
