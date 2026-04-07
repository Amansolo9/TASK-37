# Previous Inspection Errors Recheck (Static-Only)

Date: 2026-04-07
Scope: Re-checked the same previously reported issues from the prior inspection. No runtime execution, no tests run, no code changes made.

## Overall Result
- Previously reported issues rechecked: 5
- Fixed: 5
- Remaining open from previous list: 0

## Per-Issue Status

### 1) Outbox acknowledgment ownership bypass (unclaimed/direct ack)
- Status: **Fixed**
- Evidence:
  - `app/services/outbox_service.py:49-55` now blocks unclaimed ack, requires consumer name, and enforces ownership match.
  - API/GraphQL still route through the same hardened service method (`app/blueprints/api/routes.py:479`).
  - Added regression tests: `tests/test_audit4_fixes.py:41-47`, `:72-83`, `:113-124`.

### 2) Schedule CSV report filtering gap
- Status: **Fixed**
- Evidence:
  - Schedule report generation now uses filtered builder: `app/services/analytics_service.py:286` via `_build_schedule_query` at `:182-201`.
  - Region/date/status filtering is present in `_build_schedule_query` (`:190-200`).
  - Added schedule report filter tests: `tests/test_audit4_fixes.py:186-225`.

### 3) Async report estimation not filter-aware
- Status: **Fixed**
- Evidence:
  - Estimation now uses shared filtered query builders (`app/services/analytics_service.py:204-217`).
  - Shared builders reused by generation path (`app/services/analytics_service.py:272-287`).
  - Added filter-aware estimation tests: `tests/test_audit4_fixes.py:239-316`.

### 4) Blank slug creation path safety (API/CMS)
- Status: **Fixed**
- Evidence:
  - CMS service auto-derives blank/None slug from title and blocks unrecoverable blank: `app/services/cms_service.py:64-70`.
  - API still passes slug input, now safely handled by service (`app/blueprints/api/routes.py:90-92`).
  - Added tests for service and API blank slug paths: `tests/test_audit4_fixes.py:324-349`, `:428-441`.

### 5) Prior coverage gap (no unclaimed-ack tests)
- Status: **Fixed**
- Evidence:
  - Explicit service/REST/GraphQL tests for unclaimed ack denial are present:
    - `tests/test_audit4_fixes.py:41-47`
    - `tests/test_audit4_fixes.py:72-83`
    - `tests/test_audit4_fixes.py:113-124`

## Additional Note (from last recheck)
- Prior partial mismatch (`state` UI key vs `status` service key for schedule reports) is now handled.
- Evidence:
  - Route/form still submit `state` (`app/blueprints/analytics/routes.py:79-81`, `app/templates/analytics/kpis.html:42`).
  - Service now normalizes `status` or `state` (`app/services/analytics_service.py:192-194`).
  - Tests added for alias behavior and browser-form flow: `tests/test_audit4_fixes.py:227-247`, `:249-256`.
