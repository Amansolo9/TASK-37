# API Documentation

## Authentication
API clients use key-based JWT authentication.

### Obtain Token
```
POST /api/v1/auth/token
Content-Type: application/json

{
  "key_id": "your_key_id",
  "secret": "your_secret"
}

Response:
{
  "token": "eyJ...",
  "expires_in": 3600
}
```

### Using the Token
Include in Authorization header:
```
Authorization: Bearer eyJ...
```

## Scopes
API clients are assigned scopes that control access:
- `content.read` / `content.write`
- `search.read`
- `dispatch.read` / `dispatch.write`
- `orders.read` / `orders.write`
- `analytics.read`
- `files.read`
- `outbox.read` / `outbox.write`

## Quotas
- Default: 1,000 requests/day per API key
- 429 response when quota exceeded
- Counter resets daily

## REST Endpoints

### Content
| Method | Path | Scope | Description |
|--------|------|-------|-------------|
| GET | /api/v1/content | content.read | List content |
| GET | /api/v1/content/:id | content.read | Get content detail |
| POST | /api/v1/content | content.write | Create content |
| POST | /api/v1/content/:id/submit-review | content.write | Submit for review |
| POST | /api/v1/content/:id/approve | content.write | Approve and publish |
| POST | /api/v1/content/:id/schedule | content.write | Schedule publish |
| POST | /api/v1/content/:id/withdraw | content.write | Withdraw |

### Search
| Method | Path | Scope | Description |
|--------|------|-------|-------------|
| GET | /api/v1/search?q=... | search.read | Full-text search |
| GET | /api/v1/search/insights | search.read | Trending + zero results |

### Resources & Schedules
| Method | Path | Scope | Description |
|--------|------|-------|-------------|
| GET | /api/v1/resources | dispatch.read | List resources |
| POST | /api/v1/resources | dispatch.write | Create resource |
| GET | /api/v1/schedules | dispatch.read | List schedule items |
| POST | /api/v1/schedules/auto-assign | dispatch.write | Auto-assign |
| POST | /api/v1/schedules/:id/reschedule | dispatch.write | Reschedule |
| POST | /api/v1/schedules/:id/substitute | dispatch.write | Substitute |

### Service Items & Orders
| Method | Path | Scope | Description |
|--------|------|-------|-------------|
| GET | /api/v1/service-items | orders.read | List services |
| GET | /api/v1/orders | orders.read | List orders |
| POST | /api/v1/orders | orders.write | Create order |
| POST | /api/v1/orders/:id/pay | orders.write | Record payment + pay |
| POST | /api/v1/orders/:id/cancel | orders.write | Cancel order |
| POST | /api/v1/orders/:id/complete | orders.write | Complete order |
| POST | /api/v1/orders/:id/refund | orders.write | Refund order |
| POST | /api/v1/reconciliation-runs | orders.write | Create reconciliation |

### Analytics & Reports
| Method | Path | Scope | Description |
|--------|------|-------|-------------|
| GET | /api/v1/kpis | analytics.read | KPI metrics |
| POST | /api/v1/reports | analytics.read | Create report job |
| GET | /api/v1/reports/:id | analytics.read | Report job status |

### Files
| Method | Path | Scope | Description |
|--------|------|-------|-------------|
| GET | /api/v1/files/:id/download-link | files.read | Get signed, time-limited download URL |
| GET | /api/v1/files/:id/download | files.read | Download file (requires signed URL params) |

**File download flow:**
1. Call `GET /api/v1/files/:id/download-link` to get a signed URL (valid for 10 minutes)
2. Use the returned URL (includes `sig`, `expires`, `uid` params) to download the file
3. Direct access to `/download` without signed params returns 403
4. Signed URLs are bound to the authenticated principal and cannot be replayed by a different client

**Watermark support (optional visible watermark on download):**
- JPG/JPEG/PNG: visible text overlay via Pillow
- PDF: visible text watermark rendered on each page via pypdf content stream injection
- DOCX: visible watermark text added to document headers via python-docx

### Outbox Events
| Method | Path | Scope | Description |
|--------|------|-------|-------------|
| GET | /api/v1/outbox-events/pull | outbox.read | Pull pending events |
| POST | /api/v1/outbox-events/:id/ack | outbox.write | Acknowledge event |

## GraphQL

### Endpoint
```
POST /api/v1/graphql
Authorization: Bearer eyJ...
Content-Type: application/json

{
  "query": "{ contents(state: \"published\") { id title slug } }"
}
```

### Queries
- `content(id, slug)` - Single content item
- `contents(state, region_id)` - Content list
- `search(query, record_type)` - Search
- `schedules(status, region_id)` - Schedule items
- `orders(state, region_id)` - Orders
- `reportJob(id)` - Report job status

### Mutations
- `createReportJob(report_type, filters)` - Create report
- `acknowledgeOutboxEvent(id, consumer_name)` - Ack event (consumer-scoped)

## Setup

### Create API Client (Admin UI or CLI)
1. Navigate to Admin > API Clients
2. Or use the seed command which creates demo users

### Local Development
```bash
pip install -r requirements.txt
flask db upgrade  # or flask db init + migrate
flask seed
python run.py
```

API available at http://localhost:5000/api/v1/
