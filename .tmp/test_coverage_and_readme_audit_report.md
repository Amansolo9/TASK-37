# Test Coverage Audit

## Project Type Detection
- Declared type: **fullstack** (`repo/README.md` top comment: `project-type: fullstack`).

## Backend Endpoint Inventory
Scoped to API blueprints (`/api/v1` and `/api/v1/htmx`):

1. `POST /api/v1/auth/token`
2. `GET /api/v1/content`
3. `GET /api/v1/content/<id>`
4. `POST /api/v1/content`
5. `POST /api/v1/content/<id>/submit-review`
6. `POST /api/v1/content/<id>/approve`
7. `POST /api/v1/content/<id>/schedule`
8. `POST /api/v1/content/<id>/withdraw`
9. `GET /api/v1/search`
10. `GET /api/v1/search/insights`
11. `GET /api/v1/resources`
12. `POST /api/v1/resources`
13. `GET /api/v1/schedules`
14. `POST /api/v1/schedules/auto-assign`
15. `GET /api/v1/schedules/suggest`
16. `POST /api/v1/schedules/<id>/confirm-suggestion`
17. `POST /api/v1/schedules/<id>/reschedule`
18. `POST /api/v1/schedules/<id>/substitute`
19. `GET /api/v1/service-items`
20. `GET /api/v1/orders`
21. `POST /api/v1/orders`
22. `POST /api/v1/orders/<id>/pay`
23. `POST /api/v1/orders/<id>/cancel`
24. `POST /api/v1/orders/<id>/complete`
25. `POST /api/v1/orders/<id>/refund`
26. `POST /api/v1/reconciliation-runs`
27. `GET /api/v1/kpis`
28. `POST /api/v1/reports`
29. `GET /api/v1/reports/<id>`
30. `GET /api/v1/files/<id>/download-link`
31. `GET /api/v1/files/<id>/download`
32. `GET /api/v1/outbox-events/pull`
33. `POST /api/v1/outbox-events/<id>/ack`
34. `POST /api/v1/graphql`
35. `GET /api/v1/htmx/search`
36. `GET /api/v1/htmx/content`
37. `GET /api/v1/htmx/orders`
38. `GET /api/v1/htmx/schedules`
39. `GET /api/v1/htmx/kpis`

Evidence: `repo/app/blueprints/api/routes.py`, `repo/app/blueprints/htmx/routes.py`, `repo/app/__init__.py`.

## API Test Mapping Table
All 39 endpoints have direct HTTP route tests with `client.get/post(...)` in `repo/tests/api_tests/*`, including newly added `repo/tests/api_tests/test_audit7_fixes.py` for the previously uncovered 23 endpoints.

Representative evidence:
- `POST /api/v1/auth/token`: `test_audit7_fixes.py::TestAuthToken.test_token_success`
- `GET /api/v1/content/<id>`: `test_audit7_fixes.py::TestContentDetailAPI.test_get_content_detail`
- `POST /api/v1/orders/<id>/pay`: `test_audit7_fixes.py::TestOrderActionsAPI.test_pay_order`
- `POST /api/v1/reconciliation-runs`: `test_audit7_fixes.py::TestReconciliationAPI.test_create_reconciliation_run`
- `GET /api/v1/kpis`: `test_audit7_fixes.py::TestKPIsAPI.test_get_kpis`

## API Test Classification
1. True No-Mock HTTP
- Present for all 39 endpoints via Flask test client and real route handlers.
- Evidence: `repo/tests/conftest.py::client` + endpoint tests under `repo/tests/api_tests/`.

2. HTTP with Mocking
- None detected for endpoint-coverage tests.

3. Non-HTTP (unit/integration without HTTP)
- Present in `repo/tests/unit_tests/test_encryption.py`, `repo/tests/unit_tests/test_search.py`, and service-heavy API test modules.

## Mock Detection Rules Findings
Detected mocks:
- `repo/tests/api_tests/test_audit6_fixes.py`: `patch("app.services.search_service.index_schedule_item", ...)`
- `repo/tests/api_tests/test_audit4_fixes.py`: `MagicMock` usage in watermark tests
- `repo/tests/api_tests/test_audit5_fixes.py`: `MagicMock` usage in watermark tests

Classification: these are service-level tests, not endpoint HTTP coverage tests.

## Coverage Summary
- Total endpoints: **39**
- Endpoints with HTTP tests: **39**
- Endpoints with TRUE no-mock tests: **39**
- HTTP coverage: **100.00%**
- True API coverage: **100.00%**

## Unit Test Summary
### Backend Unit Tests
- Files:
  - `repo/tests/unit_tests/test_encryption.py`
  - `repo/tests/unit_tests/test_search.py`
  - plus service-focused tests in `repo/tests/api_tests/*.py`
- Covered modules: controllers/routes, auth/guards, services (cms/orders/dispatch/files/analytics/search/outbox), DB query paths.
- Important backend modules not deeply tested: some web UI route payload/detail assertions remain mostly smoke-level.

### Frontend Unit Tests (STRICT)
Frontend test files found:
- `repo/tests/unit_tests/test_frontend.py`

Framework/tools detected:
- `pytest`
- Flask test client rendering server-side frontend templates

Components/modules covered (direct evidence):
- Dashboard/nav rendering (`/dashboard`)
- Template HTMX contracts (`/orders`, `/cms/content`, `/dispatch/schedule`, `/search`)
- HTMX partial endpoints (`/api/v1/htmx/*`) response type/fragment checks
- Form structure/CSRF contracts
- Static asset inclusion and delivery (`/static/...`)

Important frontend components/modules still not tested:
- Browser-side JavaScript behavior execution in a real browser context
- Visual/regression layout checks

**Frontend unit tests: PRESENT**

### Cross-Layer Observation
- Backend and frontend tests are now substantially more balanced.
- Remaining bias: backend/API assertions are stronger than browser-behavior assertions.

## API Observability Check
- Endpoint method/path/request/response assertions are explicit for most routes.
- A subset still assert status-only without deep payload contracts.
- Verdict: **moderate to strong**.

## Test Quality & Sufficiency
- Success/failure/auth/permission cases: strong.
- Validation/edge case coverage: strong on API surface.
- Integration boundaries: strong for static analysis expectations.
- Remaining gap: no dedicated browser E2E suite.

## Tests Check
- `repo/run_tests.sh` is Docker-based (`docker compose build` + `docker compose run ... pytest`) -> **OK**.

## End-to-End Expectations
- Fullstack FE-BE E2E suite is still not explicitly present.
- Current API + unit/frontend-template tests provide strong partial compensation.

## Test Coverage Score (0–100)
**92/100**

## Score Rationale
- + 100% endpoint HTTP and true API coverage.
- + Frontend unit tests now present with direct file evidence.
- - No dedicated browser E2E tests.
- - Some status-code-only assertions remain.

## Key Gaps
1. No dedicated end-to-end browser automation suite.
2. Some tests could assert richer response payload contracts.

## Confidence & Assumptions
- Confidence: **high**.
- Static-only inspection; no commands run that execute tests/builds.

---

# README Audit

## README Location
- Exists: `repo/README.md`.

## High Priority Issues
- None.

## Medium Priority Issues
1. `Project Structure` section references files not found in `repo/docs/` in this workspace:
   - `docs/ARCHITECTURE.md`
   - `docs/API.md`
   - `docs/IMPLEMENTATION_STATUS.md`

## Low Priority Issues
1. Mentions `.env.example` but that file is not visible in current file inventory.

## Hard Gate Failures
- None.

## Hard Gate Check Results
- Formatting/readability: **PASS**
- Project type declaration at top: **PASS**
- Startup instructions for fullstack/backend include required `docker-compose up`: **PASS** (`docker-compose up --build`)
- Access method includes URL/port: **PASS** (`http://localhost:5000`)
- Verification method includes UI flow + API curl checks: **PASS**
- Environment rules (no runtime installs/manual DB setup): **PASS**
- Demo credentials with roles: **PASS**

## Engineering Quality
- Tech stack clarity: good
- Workflow/run instructions: good
- Test instructions: Docker-contained and clear
- Security/roles presentation: good

## README Verdict
**PASS**
