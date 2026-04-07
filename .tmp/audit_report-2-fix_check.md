# Previous Findings Re-Check (Check-Check Latest)

Date: 2026-04-07
Method: Static-only inspection (no runtime/tests executed)

## Summary
- Fixed: 6
- Partially Fixed: 0
- Not Fixed: 0

## Verification Results

### 1) Object-level attachment authorization
- Status: Fixed
- Evidence:
  - Browser enforcement: `app/blueprints/files/routes.py:69`, `app/blueprints/files/routes.py:91`
  - API enforcement: `app/blueprints/api/routes.py:522`, `app/blueprints/api/routes.py:557`
  - Policy helper: `app/services/access_policy.py:90`

### 2) Tenant/user data isolation
- Status: Fixed
- Evidence:
  - Region filter helper: `app/services/access_policy.py:65`
  - Region check helper for object-level access: `app/services/access_policy.py:76`
  - Page list routes apply region filter:
    - `app/blueprints/cms/routes.py:36`
    - `app/blueprints/orders/routes.py:37`
    - `app/blueprints/dispatch/routes.py:73`
  - Detail/action routes enforce region access:
    - `app/blueprints/cms/routes.py:79`
    - `app/blueprints/orders/routes.py:89`
    - `app/blueprints/api/routes.py:93`, `app/blueprints/api/routes.py:386`, `app/blueprints/api/routes.py:408`, `app/blueprints/api/routes.py:425`, `app/blueprints/api/routes.py:442`
  - API list routes apply region filter:
    - `app/blueprints/api/routes.py:80`, `app/blueprints/api/routes.py:243`, `app/blueprints/api/routes.py:356`

### 3) API report creation scope
- Status: Fixed
- Evidence:
  - `app/blueprints/api/routes.py:484`
  - Browser parity: `app/blueprints/analytics/routes.py:72`

### 4) CSRF boundary (JWT API vs HTMX)
- Status: Fixed
- Evidence:
  - JWT API blueprint CSRF exemption: `app/__init__.py:111`
  - HTMX in separate blueprint: `app/blueprints/htmx/routes.py:1`

### 5) Secret/config hardening
- Status: Fixed
- Evidence:
  - Secret validator exists: `app/config.py:40`
  - Validator called unconditionally for non-test startup: `app/__init__.py:15`, `app/__init__.py:17`

### 6) Silent exception swallowing
- Status: Fixed
- Evidence:
  - Logged exception handlers in integration paths:
    - `app/services/order_service.py:171`
    - `app/services/dispatch_service.py:74`, `app/services/dispatch_service.py:205`, `app/services/dispatch_service.py:212`, `app/services/dispatch_service.py:350`

## Notes
- Remediation test suite remains present for these concerns: `tests/test_audit6_fixes.py:3`.
- No code changes were made during this verification.
