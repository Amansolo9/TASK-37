# GreenCycle Operations & Content Portal

An offline-first Flask + HTMX application for municipal sustainability content management, operational scheduling, service catalog/order lifecycle, and analytics reporting.

## Quick Start

### Prerequisites
- Python 3.12+
- pip

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Initialize the database
export FLASK_APP=wsgi.py
flask db upgrade

# Seed demo data (idempotent)
flask seed

# Run the development server (includes background scheduler)
python run.py
```

The app starts at **http://localhost:5000**.

### Docker

```bash
docker compose up --build
```

This builds the image, runs migrations, seeds data, and starts the app with gunicorn on port 5000.

## Demo Accounts

| Username | Password | Role |
|----------|----------|------|
| admin | admin123 | Full admin access |
| editor | editor123 | Content creation/editing |
| reviewer | reviewer123 | Content review/publish |
| dispatcher | dispatch123 | Resource/schedule management |
| analyst | analyst123 | Analytics/reporting (read-only) |

## Configuration

Copy `.env.example` and set values. Key settings:

| Variable | Default | Description |
|----------|---------|-------------|
| SECRET_KEY | dev-secret | Flask session secret (change in production) |
| JWT_SECRET_KEY | dev-jwt-secret | API JWT signing key |
| FIELD_ENCRYPTION_KEY | **(required)** | Fernet key for encrypted fields — generate via `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| SQLITE_PATH | instance/greencycle.db | Database file location |
| STORAGE_ROOT | storage | File upload/archive root |
| MAX_UPLOAD_MB | 20 | Max upload file size |
| API_DAILY_QUOTA | 1000 | API requests per key per day |
| SCHEDULER_ENABLED | true | Set false to disable background jobs |

See `.env.example` for the full list.

## Running Tests

```bash
python -m pytest tests/ -v
```

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

## Offline-First

All assets (Bootstrap 5, HTMX, Quill editor) are bundled locally. No internet dependency for any feature.
