# Architecture

## Overview
GreenCycle Operations & Content Portal is an offline-first Flask application for municipal sustainability content management, operational scheduling, service catalog/order lifecycle, and analytics.

## Stack
- **Backend**: Python 3.12+, Flask 3.x, SQLAlchemy 2.x
- **Database**: SQLite with WAL mode, FTS5 for search
- **Frontend**: Jinja2 templates + HTMX + Bootstrap 5 (all served locally)
- **Rich Text**: Quill 1.3.7 (bundled)
- **Auth**: Argon2 password hashing, Flask-Login sessions, PyJWT for APIs
- **Background Jobs**: APScheduler (in-process)
- **Encryption**: cryptography/Fernet for sensitive fields

## Architecture Decisions

### Offline-First
All assets served locally. No CDNs, external APIs, SaaS services, or cloud dependencies. The application is fully functional without internet access.

### Service Layer Architecture
Flask page routes, HTMX partials, REST endpoints, and GraphQL resolvers all call the same service functions (app/services/). No business logic lives in routes.

### HTMX + Decoupled API
HTMX partial-refresh interactions (search filtering, list filtering, KPI updates) consume decoupled API endpoints under `/api/v1/htmx/*` rather than page routes. This separation ensures:
- **Page routes** handle initial full-page composition only
- **API HTMX endpoints** serve filtered HTML partials using the same service layer and templates
- **REST/JSON endpoints** under `/api/v1/*` serve JSON for programmatic API clients
- All three layers share the same service functions, ensuring consistent business logic

The HTMX endpoints use Flask-Login session authentication (for browser use) while REST endpoints use JWT authentication (for API clients).

### CSRF Blueprint Separation
- **JWT API blueprint** (`/api/v1/*`): CSRF-exempt, token-authenticated for programmatic clients
- **HTMX API blueprint** (`/api/v1/htmx/*`): CSRF-protected, session-authenticated for browser HTMX

### Data Isolation Model
Region-based isolation is enforced via `app/services/access_policy.py`:
- **Admin users** see all data across all regions
- **Non-admin users** see data scoped to regions associated with their created entities, or all active regions if they hold broad operational permissions
- **Attachment access** is enforced per-object: uploader always allowed, admin always allowed, owner-relationship checked for owned attachments, deny-by-default for unknown owner types
- **File lists** are scoped: non-admin users see only their own uploads
- The isolation boundary is applied in HTMX partials, browser routes, and API paths via shared query helpers

### SQLite Optimization
- WAL mode for concurrent readers
- Foreign keys enforced
- 5-second busy timeout
- FTS5 for full-text search
- Indexes on workflow_state, dates, and foreign keys

### Authentication
- Username/password only (no OAuth/SSO)
- Argon2 for password hashing (salted, memory-hard)
- Account lockout: 5 failures -> 15 minute lockout
- Session timeout: 30 minute idle
- CSRF protection via Flask-WTF on all browser forms
- JWT for API clients (separate from session auth)

### Encrypted Fields
Fernet symmetric encryption for service addresses and other sensitive data. Encryption key from config. Only decrypted when authorized user explicitly requests it.

### Payment Model
Internal offline payment records only. Tender types: cash, check, invoice. Receipt number required. No external payment gateway integration.

### Reconciliation
Delta threshold of $5.00. Absolute difference exceeding threshold is flagged for review. Status tracked per reconciliation run.

### File Storage
Files stored in non-public directory (storage/uploads/). Never served from static path. Signed URLs with HMAC verification and expiry. Watermarks applied on-demand, never mutating originals.

### Date Handling
- UI display: MM/DD/YYYY
- Database/API: ISO 8601
- Conversion at boundary (parse_date_us / format_date_us)

## Module Map

```
app/
├── __init__.py          # App factory
├── config.py            # Configuration
├── extensions.py        # Flask extension instances
├── models/              # SQLAlchemy models
├── services/            # Business logic (reused across UI/API/GraphQL)
│   ├── auth_service.py
│   ├── admin_service.py
│   ├── cms_service.py
│   ├── search_service.py
│   ├── dispatch_service.py
│   ├── order_service.py
│   ├── analytics_service.py
│   ├── file_service.py
│   ├── outbox_service.py
│   ├── api_auth_service.py
│   └── audit_service.py
├── blueprints/          # Flask blueprints (routes only)
├── graphql/             # GraphQL schema
├── forms/               # WTForms
├── templates/           # Jinja2 templates
├── static/              # CSS, JS, vendor assets
├── tasks/               # Scheduler, seed command
└── utils/               # Helpers (encryption, dates, auth, pagination)
```

## Background Jobs

APScheduler runs four background jobs:
- **Scheduled Publish** (every 1 min): publishes content at scheduled_publish_at
- **Report Processor** (every 30 sec): processes queued CSV report jobs
- **Attachment Archive** (daily 2 AM): moves old uploads to archive
- **Attachment Purge** (daily 3 AM): deletes expired files if ENABLE_FILE_PURGE=true

### Deployment model
The scheduler starts at module-import time in `run.py`. Under gunicorn with `--preload`, the module loads once in the master process before forking workers, so jobs run exactly once. The Docker setup uses this approach.

For alternative deployments:
- Set `SCHEDULER_ENABLED=false` to disable the scheduler in web workers
- Run `python -m app.tasks.run_scheduler` as a dedicated scheduler process

### Report Async Policy
Reports estimated to take > 5 seconds (based on row count / 100 rows-per-second heuristic) are generated asynchronously. Smaller reports run synchronously. The estimation rate (_ROWS_PER_SECOND) can be tuned based on observed performance.

## Security Notes
- All user inputs sanitized (Bleach for HTML, WTForms for forms)
- SQL injection prevented by SQLAlchemy ORM
- Path traversal prevented in file operations
- CSRF on all browser forms
- Signed download URLs re-check permissions
- Sensitive fields masked in list views unless authorized
- Device identifiers and credit history encrypted at rest (Fernet) alongside service addresses
- Sensitive field decryption gated by analytics.view_financials permission
- API/GraphQL expose boolean presence flags, never raw encrypted values
- Audit logging for security-relevant actions
