# Questions and Solutions

## 1. Account Lockout Recovery Without Admin Intervention

**Question:** The prompt states accounts lock for 15 minutes after 5 failed attempts. What happens if a legitimate user is locked out and there is no administrator available, or if an attacker deliberately locks out critical accounts (e.g., the sole Administrator)?

**My Understanding:** A fixed-duration lockout is standard, but in an offline system with no password-reset email flow, there must be a path to recovery that doesn't depend on another online user.

**Solution:** The system implements a time-based automatic unlock in `app/services/auth_service.py`. The `authenticate_user()` function checks `user.lockout_until` against `datetime.utcnow()` on every login attempt. Once the 15-minute window elapses, the lockout clears automatically—no admin action needed. On successful login the counter resets (`failed_login_attempts = 0`, `lockout_until = None`). The lockout threshold (5) and duration (15 min) are configurable via `LOGIN_LOCKOUT_THRESHOLD` and `LOGIN_LOCKOUT_MINUTES` in `app/config.py`, so deployments under targeted lockout attacks can raise the threshold or shorten the window.

---

## 2. Order State Machine Enforcement for Illegal Transitions

**Question:** The prompt defines an order lifecycle (created, paid, canceled, completed, refunded) but does not specify what happens if a client attempts an illegal transition—for example, trying to refund a "created" order that was never paid.

**My Understanding:** Without strict enforcement, API consumers or UI bugs could corrupt order state, causing reconciliation mismatches and financial reporting errors.

**Solution:** The codebase enforces a whitelist of valid transitions via the `ORDER_TRANSITIONS` dictionary in `app/services/order_service.py`: `created` may move to `[paid, canceled]`, `paid` to `[completed, refunded]`, `completed` to `[refunded]`, and `canceled`/`refunded` are terminal states with no outgoing transitions. The `transition_order()` function raises a `ValueError` if the requested state is not in the allowed list for the current state. Additionally, the `paid` transition requires at least one Payment record to exist, preventing empty payment transitions. Each transition stamps a dedicated timestamp (`paid_at`, `completed_at`, etc.) and emits an outbox event (`order.paid`, `order.completed`, etc.) for downstream consumers.

---

## 3. Reconciliation Mismatch Below the $5.00 Threshold

**Question:** The prompt says mismatches over $5.00 are flagged for review. How does the system handle mismatches that are under $5.00 but nonzero—do they silently disappear, or is there an audit trail?

**My Understanding:** Small discrepancies still need to be recorded for auditing purposes, even if they don't trigger a review workflow.

**Solution:** In `app/services/order_service.py`, the `create_reconciliation_run()` function records every order in the run as a `ReconciliationItem` regardless of delta size. The `delta_amount` is always stored with `Decimal("0.01")` quantization. If `abs(delta) > RECONCILIATION_THRESHOLD` (which is `Decimal("5.00")`), the item's `flagged_for_review` boolean is set to `True` and its status becomes `"flagged"`. Below-threshold items are stored with status `"matched"` and `flagged_for_review = False`. The Order model itself also receives `reconciliation_status` and `reconciliation_delta` fields, so every order retains its reconciliation result for reporting regardless of whether it was flagged.

---

## 4. File Upload Spoofing (Extension vs. Actual Content)

**Question:** The prompt requires a whitelist of PDF, JPG/PNG, DOCX with MIME/extension consistency checks. But what if an attacker renames an executable to `.pdf` and sends a matching `Content-Type: application/pdf` header—both the extension and declared MIME would pass?

**My Understanding:** Relying solely on client-declared MIME type is insufficient. The system must inspect actual file bytes to detect content-type mismatches.

**Solution:** The system implements magic-byte sniffing in `app/services/file_service.py`. A `_MAGIC_SIGNATURES` dictionary maps file header bytes to actual content types (`b"%PDF"` for PDF, `b"\xff\xd8\xff"` for JPEG, `b"\x89PNG"` for PNG, `b"PK\x03\x04"` for DOCX). The `_sniff_mime()` function reads the first 16 bytes of the uploaded file and compares the detected type against the extension's allowed MIME set from `MIME_MAP`. If the sniffed type does not match what the extension expects, the upload is rejected—even if the client-supplied `Content-Type` header was correct. Additionally, a `BLOCKED_EXTENSIONS` set (exe, bat, cmd, msi, scr, ps1, sh, jar, py, etc.) is checked before MIME validation, providing defense in depth.

---

## 5. Scheduled Publish Timing Drift

**Question:** The prompt mentions "scheduled publish" as a content state, but does not specify how the system guarantees a piece of content goes live at or near its scheduled time, especially in an offline system without an external job scheduler.

**My Understanding:** Without a reliable background process, scheduled content could remain unpublished indefinitely if the check only runs on user-triggered requests.

**Solution:** The system uses APScheduler's `BackgroundScheduler` configured in `app/tasks/scheduler.py`. The `scheduled_publish_job` runs on a 1-minute interval. It calls `process_scheduled_publishes()` in `app/services/cms_service.py`, which queries for all `ContentItem` records where `workflow_state == "scheduled"` and `scheduled_publish_at <= datetime.utcnow()`. Matching items are transitioned to `"published"`, stamped with `published_at`, indexed into FTS5 search, and an outbox event `"content.published"` is emitted. The maximum drift is therefore ~1 minute. For production multi-worker deployments, `SCHEDULER_ENABLED` can be set to `false` on web workers while a dedicated scheduler process (`python -m app.tasks.run_scheduler`) runs independently, preventing duplicate job execution.

---

## 6. Search Degradation When FTS5 Is Unavailable

**Question:** The system uses SQLite FTS5 for full-text search. What happens if the FTS5 virtual table becomes corrupted or the SQLite build does not include the FTS5 extension?

**My Understanding:** Search is a core user-facing feature. A hard dependency on FTS5 without a fallback would render the search page non-functional.

**Solution:** The `search()` function in `app/services/search_service.py` implements a two-tier strategy. It first attempts an FTS5 `MATCH` query against the `search_fts` virtual table. If the FTS query raises any exception (corruption, missing extension, syntax error), it falls back to a `LIKE`-based search across `title`, `body_text`, and `tags_text` fields of the `SearchDocument` table. The LIKE fallback applies the same facet filters (record_type, region_id, media_type, date range, category_id), deterministic ordering (`updated_at DESC, id DESC`), and pagination (`offset`/`limit`). A `rebuild_fts_index()` function is available to reconstruct the FTS table via `INSERT INTO search_fts(search_fts) VALUES('rebuild')` if corruption is detected.

---

## 7. Scheduling Conflicts That Cannot Be Auto-Resolved

**Question:** The prompt mentions automatic and semi-automatic scheduling with conflict detection for double-booked instructors, overlapping rooms, and time-slot violations. What happens when the auto-assign algorithm cannot place an item without creating a conflict?

**My Understanding:** A greedy algorithm will hit dead ends. The system needs a way to surface unresolvable conflicts to dispatchers rather than silently skipping items or creating invalid assignments.

**Solution:** The `detect_conflicts()` function in `app/services/dispatch_service.py` runs after every assignment and checks three conditions: instructor overlap (same instructor, same date, overlapping start/end times), classroom overlap (same room, same date, overlapping times), and time-slot template violations (item times outside template bounds). When conflicts are found, `ScheduleConflict` records are created with typed severity (`"error"` for overlaps, `"warning"` for slot violations) and the item's status is set to `"conflict"` rather than `"scheduled"`. Dispatchers see these flagged items on the schedule board and can use the reschedule workflow (change time/date/resource) or substitute workflow (swap instructor/room) to resolve them. A `suggest_assignments()` function provides semi-automatic mode—it scores candidates by conflict count and region-match bonus, returning the top 5 options without committing, so the dispatcher makes the final call via `confirm_suggestion()`.

---

## 8. API Quota Reset Timing and Multi-Key Abuse

**Question:** The prompt specifies 1,000 requests/day per API key. When exactly does the counter reset, and what prevents a consumer from creating multiple API keys to multiply their effective quota?

**My Understanding:** "Daily" is ambiguous without a defined reset boundary, and without creation controls a single consumer could trivially bypass quotas.

**Solution:** In `app/services/api_auth_service.py`, the `check_quota()` function uses `date.today()` as the partition key in the `ApiUsageCounter` table (unique constraint on `api_client_id + usage_date`). The counter resets at midnight server-local time when a new date creates a new counter row. The daily quota value (`API_DAILY_QUOTA = 1000`) is configurable in `app/config.py`. API client creation is gated behind the `admin.manage_api_keys` permission—only Administrators can create new clients via the Admin UI (`/admin/api-clients/new`). Secrets are Argon2-hashed and shown only once at creation time. Administrators can revoke any client via POST to `/admin/api-clients/<id>/revoke`, and the `jwt_required` decorator checks active status on every request, so revoked clients are immediately blocked even if their JWT hasn't expired.

---

## 9. Signed Download URL Replay by Different Users

**Question:** The prompt requires signed, time-limited download URLs (10 minutes) with permission checks. Can a user who obtains a valid signed URL share it with an unauthorized user who then downloads the file within the 10-minute window?

**My Understanding:** If the signed URL only encodes the file ID and expiry, any bearer could use it. The URL must be bound to the requesting principal.

**Solution:** The `generate_signed_url()` function in `app/services/file_service.py` includes the `user_id` in the HMAC payload: `f"{attachment_id}:{user_id}:{expires}"`. The signature is computed with `hmac.new(SECRET_KEY, payload, hashlib.sha256)`. On verification, `verify_signed_url()` reconstructs the same payload with the provided `uid` parameter and uses `hmac.compare_digest()` for timing-safe comparison. Additionally, the `api_file_download` route verifies that the `uid` in the signed URL matches the currently authenticated principal—if principal A obtains a signed URL and principal B attempts to use it, the request returns 403 with a "different principal" message. Object-level access is also enforced via `can_access_attachment()` in `app/services/access_policy.py`, checking uploader ownership, admin status, and owner-relationship before serving any file.

---

## 10. Outbox Event Delivery Guarantees in an Offline System

**Question:** The prompt describes webhook-style event delivery implemented as an internal outbox/queue. How does the system guarantee that events are not lost or double-processed when there are no external message brokers and the system may restart at any time?

**My Understanding:** In an offline-first system without Redis or RabbitMQ, the database itself must serve as the durable queue with at-least-once delivery semantics.

**Solution:** The outbox system in `app/services/outbox_service.py` uses SQLite as the durable event store. `create_event()` writes an `OutboxEvent` row with `status="pending"` in the same database transaction as the business operation (e.g., order state change), ensuring atomicity. Consumers call `pull_events(consumer_name)` which claims unclaimed pending events by setting `consumer_name` on each row—this prevents other consumers from pulling the same events. After processing, consumers call `acknowledge_event(event_id, consumer_name)` which verifies consumer ownership (the event's `consumer_name` must match), rejects unclaimed or cross-consumer acks, and sets `status="delivered"` with a `delivered_at` timestamp. Events that are pulled but never acknowledged remain in "pending" state and will be re-pulled on the next call. This provides at-least-once delivery without any external dependencies. The optional webhook push delivery (gated by `EXTERNAL_INTEGRATIONS_ENABLED`) is additive and only targets `local_only` subscriptions with a 5-second timeout per request.

---

## 11. Sensitive Field Exposure Through API and GraphQL

**Question:** The prompt requires encrypted-at-rest sensitive fields (addresses, device identifiers, credit history) and role-based masking. How does the system prevent accidental exposure of raw encrypted or decrypted values through the REST API or GraphQL layer?

**My Understanding:** Encryption at rest protects against database theft, but if API serializers blindly include decrypted fields, the encryption is bypassed for any authenticated caller.

**Solution:** The system uses a layered defense. In the Order model, sensitive fields are stored as `encrypted_service_address`, `encrypted_device_identifier`, and `encrypted_credit_history` using Fernet encryption (`app/utils/encryption.py`). The REST API serializer in the orders blueprint never includes raw values—instead it exposes only boolean presence flags (`has_device_identifier`, `has_credit_history`). The GraphQL `OrderType` schema similarly includes only boolean flag fields. On the browser side, the order detail template checks for the `analytics.view_financials` permission before calling decryption helpers (`get_decrypted_device_identifier()`, `get_decrypted_credit_history()`); without that permission, values display as masked strings via `mask_value()` (showing only the last 4 characters). Payment receipt identifiers are also masked to the first 3 characters plus `"***"` in audit log payloads, preventing sensitive data leakage through the audit trail.

---

## 12. Session Timeout Behavior During Active HTMX Interactions

**Question:** The prompt requires a 30-minute session idle timeout. HTMX makes frequent partial requests (inline validation, filter refresh, modal edits). Do these background requests reset the idle timer, potentially keeping sessions alive indefinitely while a user has a tab open?

**My Understanding:** If every HTMX request resets the timer, the timeout becomes meaningless for users with auto-refreshing dashboards. If HTMX requests don't reset it, users could be logged out mid-workflow.

**Solution:** The session timeout is implemented as a `@app.before_request` middleware in `app/__init__.py`. On every request (including HTMX partials), it checks `current_user.last_activity_at` against `datetime.utcnow()`. If the gap exceeds `SESSION_TIMEOUT_MINUTES` (30, configurable in `app/config.py`), it calls `logout_user()` and `session.clear()`. Otherwise, it updates `last_activity_at = now`. This means HTMX requests do reset the timer—any user interaction (filter change, search keystroke, modal open) counts as activity. The design treats this as correct behavior: if the user is actively interacting with the page, they are not idle. A truly idle user (tab open but no clicks/filters for 30 minutes) will be logged out on their next interaction. For API paths (`/api/*`), the middleware silently logs out without redirect, since API clients use JWT authentication rather than sessions.
