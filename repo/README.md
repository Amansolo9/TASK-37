<!-- project-type: fullstack -->
# GreenCycle Operations & Content Portal

An offline-first Flask + HTMX application for municipal sustainability content management, operational scheduling, service catalog/order lifecycle, and analytics reporting.

## Quick Start

### Prerequisites
- Docker and Docker Compose

### Startup

```bash
docker-compose up --build
```

This builds the image, runs migrations, seeds demo data, and starts the app with gunicorn on port 5000.

The app is available at **http://localhost:5000**.

## Demo Accounts

| Username | Password | Role |
|----------|----------|------|
| admin | admin123 | Full admin access |
| editor | editor123 | Content creation/editing |
| reviewer | reviewer123 | Content review/publish |
| dispatcher | dispatch123 | Resource/schedule management |
| analyst | analyst123 | Analytics/reporting (read-only) |

## Verification

After startup, verify the system is running correctly:

### UI Verification
1. Open **http://localhost:5000** in a browser.
2. Log in with `admin` / `admin123`.
3. Confirm the dashboard loads with navigation for Orders, CMS, Dispatch, Analytics, and Files.
4. Navigate to **Orders** and confirm the order list renders.
5. Navigate to **CMS > Content** and confirm the content list renders.
6. Navigate to **Dispatch > Schedule** and confirm the schedule view renders.

### API Verification

```bash
# 1. Obtain a JWT token (use an API client created via Admin > API Keys)
curl -s -X POST http://localhost:5000/api/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"key_id": "<YOUR_KEY_ID>", "secret": "<YOUR_SECRET>"}'

# 2. List content (replace <TOKEN> with the token from step 1)
curl -s http://localhost:5000/api/v1/content \
  -H "Authorization: Bearer <TOKEN>"

# 3. List orders
curl -s http://localhost:5000/api/v1/orders \
  -H "Authorization: Bearer <TOKEN>"

# 4. Get KPI metrics
curl -s http://localhost:5000/api/v1/kpis \
  -H "Authorization: Bearer <TOKEN>"
```

All endpoints should return HTTP 200 with JSON payloads.

## Running Tests

```bash
./run_tests.sh          # run full suite
./run_tests.sh unit     # unit tests only
./run_tests.sh api      # API/integration tests only
```

Tests run inside a Docker container. No local Python install is required.

## Configuration

Key environment variables are set in `docker-compose.yml`. Override them as needed:

| Variable | Default | Description |
|----------|---------|-------------|
| SECRET_KEY | (set in compose) | Flask session secret (change in production) |
| JWT_SECRET_KEY | (set in compose) | API JWT signing key |
| FIELD_ENCRYPTION_KEY | **(required)** | Fernet key for encrypted fields -- generate via `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| SQLITE_PATH | instance/greencycle.db | Database file location |
| STORAGE_ROOT | storage | File upload/archive root |
| MAX_UPLOAD_MB | 20 | Max upload file size |
| API_DAILY_QUOTA | 1000 | API requests per key per day |
| SCHEDULER_ENABLED | true | Set false to disable background jobs |

See `.env.example` for the full list.

## Background Scheduler

The app runs four background jobs via APScheduler:

- **Scheduled Publish** (every 1 min): publishes content at scheduled times
- **Report Processor** (every 30 sec): processes queued CSV report jobs
- **Attachment Archive** (daily 2 AM): moves old uploads to archive
- **Attachment Purge** (daily 3 AM): deletes expired files if enabled

### Multi-worker deployment

When running with gunicorn, use `--preload` so the scheduler starts once in the master process. The Docker setup does this by default.

To run the scheduler as a separate process instead:

```bash
SCHEDULER_ENABLED=false gunicorn "run:app" --workers 4
python -m app.tasks.run_scheduler  # in a separate process
```

## Project Structure

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for detailed architecture.

See [docs/API.md](docs/API.md) for REST and GraphQL API documentation.

See [docs/IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md) for implementation checklist.

## Offline-First

All assets (Bootstrap 5, HTMX, Quill editor) are bundled locally. No internet dependency for any feature.
