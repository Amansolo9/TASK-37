"""Tests for all audit fix items A-K.

Covers: GraphQL scope enforcement, REST actor attribution, report object-level access,
file MIME validation, analytics date parsing, semi-auto scheduling, search facets,
analyst seed permissions, open redirect protection.
"""

import io
import json
import pytest
from datetime import date, time, timedelta, datetime
from decimal import Decimal
from werkzeug.datastructures import FileStorage

from app.services import api_auth_service, cms_service, dispatch_service
from app.services import order_service, search_service, analytics_service, file_service
from app.models.dispatch import Resource, ScheduleItem, TimeSlotTemplate
from app.models.catalog import ServiceItem, Order
from app.models.analytics import ReportJob
from app.models.region import Region, Category, Tag
from app.models.search import SearchDocument
from app.extensions import db
from app.utils.auth_context import is_safe_redirect_url


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_file(filename, content, content_type):
    return FileStorage(
        stream=io.BytesIO(content),
        filename=filename,
        content_type=content_type,
    )


def _api_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _get_token(app, db, admin_user, scopes):
    """Create an API client with given scopes and return a JWT token."""
    cl, secret = api_auth_service.create_api_client("test-client", scopes, admin_user.id)
    cl_obj, _ = api_auth_service.authenticate_api_client(cl.key_id, secret)
    return api_auth_service.generate_jwt(cl_obj)


# ── A. GraphQL Authorization ────────────────────────────────────────────────

class TestGraphQLAuthorization:
    def test_graphql_denied_without_scope(self, client, app, db, admin_user):
        """GraphQL queries should be denied when JWT lacks required scope."""
        token = _get_token(app, db, admin_user, [])  # no scopes
        resp = client.post("/api/v1/graphql",
            headers=_api_headers(token),
            data=json.dumps({"query": '{ contents { id title } }'}))
        data = resp.get_json()
        assert "errors" in data
        assert any("content.read" in e["message"] for e in data["errors"])

    def test_graphql_allowed_with_correct_scope(self, client, app, db, admin_user):
        """GraphQL queries should work with the correct scope."""
        token = _get_token(app, db, admin_user, ["content.read"])
        resp = client.post("/api/v1/graphql",
            headers=_api_headers(token),
            data=json.dumps({"query": '{ contents { id title } }'}))
        data = resp.get_json()
        assert "data" in data
        assert "errors" not in data or data["errors"] is None

    def test_graphql_wrong_scope_denied(self, client, app, db, admin_user):
        """GraphQL query with wrong scope should fail."""
        token = _get_token(app, db, admin_user, ["orders.read"])  # wrong scope
        resp = client.post("/api/v1/graphql",
            headers=_api_headers(token),
            data=json.dumps({"query": '{ contents { id } }'}))
        data = resp.get_json()
        assert "errors" in data

    def test_graphql_mutation_uses_actor_id(self, client, app, db, admin_user):
        """GraphQL createReportJob mutation should use authenticated actor, not hardcoded."""
        token = _get_token(app, db, admin_user, ["analytics.read"])
        resp = client.post("/api/v1/graphql",
            headers=_api_headers(token),
            data=json.dumps({
                "query": 'mutation { createReportJob(report_type: "orders") { id status } }'
            }))
        data = resp.get_json()
        assert "data" in data
        job_id = data["data"]["createReportJob"]["id"]
        job = db.session.get(ReportJob, job_id)
        assert job.requested_by == admin_user.id  # not hardcoded 1

    def test_graphql_report_access_denied_for_non_owner(self, client, app, db, admin_user, editor_user):
        """GraphQL reportJob query should deny access to non-owner."""
        job = ReportJob(report_type="orders", requested_by=admin_user.id, status="completed")
        db.session.add(job)
        db.session.commit()

        # Create API client owned by editor
        cl, secret = api_auth_service.create_api_client("editor-client", ["analytics.read"], editor_user.id)
        cl_obj, _ = api_auth_service.authenticate_api_client(cl.key_id, secret)
        token = api_auth_service.generate_jwt(cl_obj)

        resp = client.post("/api/v1/graphql",
            headers=_api_headers(token),
            data=json.dumps({"query": f'{{ reportJob(id: {job.id}) {{ id status }} }}'}))
        data = resp.get_json()
        assert "errors" in data
        assert any("denied" in e["message"].lower() for e in data["errors"])


# ── B. REST API Actor Attribution ────────────────────────────────────────────

class TestRESTActorAttribution:
    def test_content_create_ignores_client_author_id(self, client, app, db, admin_user, region):
        """POST /content should not accept client-supplied author_id."""
        token = _get_token(app, db, admin_user, ["content.write", "content.read"])
        resp = client.post("/api/v1/content",
            headers=_api_headers(token),
            data=json.dumps({
                "title": "Test", "slug": "test-actor",
                "body_html": "<p>Test</p>", "author_id": 9999,
            }))
        assert resp.status_code == 201
        data = resp.get_json()
        from app.models.cms import ContentItem
        item = db.session.get(ContentItem, data["id"])
        assert item.created_by == admin_user.id  # actor from JWT, not 9999

    def test_order_create_uses_jwt_actor(self, client, app, db, admin_user, region):
        """POST /orders should use JWT actor for created_by."""
        svc = ServiceItem(code="API-SVC", name="API Svc", pricing_model="per_use",
                         unit_rate=Decimal("10.00"), taxable=True, active=True)
        db.session.add(svc)
        db.session.commit()

        token = _get_token(app, db, admin_user, ["orders.write"])
        resp = client.post("/api/v1/orders",
            headers=_api_headers(token),
            data=json.dumps({
                "customer_name": "Actor Test", "region_id": region.id,
                "line_items": [{"service_item_id": svc.id, "quantity": 1}],
            }))
        assert resp.status_code == 201
        data = resp.get_json()
        order = db.session.get(Order, data["id"])
        assert order.created_by == admin_user.id


# ── C. Report Object-Level Access ───────────────────────────────────────────

class TestReportObjectAccess:
    def test_api_report_access_denied_for_non_owner(self, client, app, db, admin_user, editor_user):
        """API report detail should deny access to non-owner without elevated perms."""
        job = ReportJob(report_type="orders", requested_by=admin_user.id, status="completed")
        db.session.add(job)
        db.session.commit()

        cl, secret = api_auth_service.create_api_client("other-client", ["analytics.read"], editor_user.id)
        cl_obj, _ = api_auth_service.authenticate_api_client(cl.key_id, secret)
        token = api_auth_service.generate_jwt(cl_obj)

        resp = client.get(f"/api/v1/reports/{job.id}", headers=_api_headers(token))
        assert resp.status_code == 403

    def test_api_report_access_allowed_for_owner(self, client, app, db, admin_user):
        """API report detail should allow access to report owner."""
        job = ReportJob(report_type="orders", requested_by=admin_user.id, status="completed")
        db.session.add(job)
        db.session.commit()

        token = _get_token(app, db, admin_user, ["analytics.read"])
        resp = client.get(f"/api/v1/reports/{job.id}", headers=_api_headers(token))
        assert resp.status_code == 200

    def test_browser_report_denied_for_non_owner(self, client, app, db, admin_user, editor_role):
        """Browser report detail should deny non-owner even with analytics.view."""
        from app.models.user import User, Role, RolePermission
        from app.utils.auth_helpers import hash_password
        # Create a user who has analytics.view but is not the report owner
        viewer_role = Role(name="viewer_test", description="Viewer")
        db.session.add(viewer_role)
        db.session.flush()
        for p in ["analytics.view", "analytics.export"]:
            db.session.add(RolePermission(role_id=viewer_role.id, permission=p))
        viewer = User(username="viewer_test", display_name="Viewer",
                     password_hash=hash_password("viewerpass"), is_active_user=True)
        viewer.roles.append(viewer_role)
        db.session.add(viewer)
        db.session.commit()

        job = ReportJob(report_type="orders", requested_by=admin_user.id, status="completed")
        db.session.add(job)
        db.session.commit()

        client.post("/login", data={"username": "viewer_test", "password": "viewerpass"})
        resp = client.get(f"/analytics/reports/{job.id}", follow_redirects=True)
        assert b"Access denied" in resp.data

    def test_browser_report_allowed_for_owner(self, client, app, db, logged_in_admin):
        """Browser report detail should work for report owner."""
        job = ReportJob(report_type="orders", requested_by=logged_in_admin.id, status="completed")
        db.session.add(job)
        db.session.commit()

        resp = client.get(f"/analytics/reports/{job.id}")
        assert resp.status_code == 200


# ── D. File MIME/Extension Validation ────────────────────────────────────────

class TestFileStrictMIME:
    def test_pdf_correct_mime_accepted(self, app):
        with app.app_context():
            f = _make_file("doc.pdf", b"%PDF-1.4 test", "application/pdf")
            ok, err = file_service.validate_upload(f)
            assert ok is True

    def test_pdf_wrong_mime_rejected(self, app):
        """A .pdf with image/png MIME should be rejected."""
        with app.app_context():
            f = _make_file("fake.pdf", b"%PDF-1.4 test", "image/png")
            ok, err = file_service.validate_upload(f)
            assert ok is False
            assert "not allowed" in err.lower()

    def test_png_with_jpeg_mime_rejected(self, app):
        """A .png file claiming to be image/jpeg should be rejected."""
        with app.app_context():
            f = _make_file("photo.png", b"\x89PNG\r\n", "image/jpeg")
            ok, err = file_service.validate_upload(f)
            assert ok is False

    def test_jpg_correct_mime_accepted(self, app):
        with app.app_context():
            f = _make_file("photo.jpg", b"\xff\xd8\xff test", "image/jpeg")
            ok, err = file_service.validate_upload(f)
            assert ok is True

    def test_docx_wrong_mime_rejected(self, app):
        with app.app_context():
            f = _make_file("doc.docx", b"PK test", "application/pdf")
            ok, err = file_service.validate_upload(f)
            assert ok is False

    def test_missing_mime_rejected(self, app):
        """Upload without MIME type should be rejected."""
        with app.app_context():
            f = _make_file("doc.pdf", b"%PDF-1.4 test", "")
            ok, err = file_service.validate_upload(f)
            assert ok is False
            assert "required" in err.lower()

    def test_exe_disguised_as_pdf_blocked(self, app):
        """An .exe file renamed to .pdf should still be caught by extension."""
        with app.app_context():
            f = _make_file("malware.exe", b"MZ test", "application/pdf")
            ok, err = file_service.validate_upload(f)
            assert ok is False
            assert "blocked" in err.lower()


# ── E. Analytics Date Filtering ──────────────────────────────────────────────

class TestAnalyticsDateFiltering:
    def test_parse_filter_date_iso(self, app):
        with app.app_context():
            result = analytics_service._parse_filter_date("2024-06-15")
            assert result is not None
            assert result.year == 2024
            assert result.month == 6

    def test_parse_filter_date_us_format(self, app):
        with app.app_context():
            result = analytics_service._parse_filter_date("06/15/2024")
            assert result is not None
            assert result.month == 6
            assert result.day == 15

    def test_parse_filter_date_invalid(self, app):
        with app.app_context():
            result = analytics_service._parse_filter_date("not-a-date")
            assert result is None

    def test_parse_filter_date_none(self, app):
        with app.app_context():
            result = analytics_service._parse_filter_date(None)
            assert result is None

    def test_kpi_date_filters_applied(self, app, db, admin_user, region):
        """KPI queries with date filters should use parsed dates."""
        svc = ServiceItem(code="DT-001", name="Date Test", pricing_model="per_use",
                         unit_rate=Decimal("50.00"), taxable=False, active=True)
        db.session.add(svc)
        db.session.commit()
        order = order_service.create_order(
            "Date Corp", region.id, admin_user.id,
            line_items=[{"service_item_id": svc.id, "quantity": 1}])
        # Filter for a future date range should exclude the order
        metrics = analytics_service.get_kpis("orders", {"date_from": "2099-01-01"})
        assert metrics["order_count"] == 0

    def test_kpi_invalid_date_ignored(self, app, db):
        """Invalid date string should not crash, just be ignored."""
        metrics = analytics_service.get_kpis("orders", {"date_from": "garbage"})
        assert "order_count" in metrics  # should still return results


# ── F. Semi-Automatic Scheduling ────────────────────────────────────────────

class TestSemiAutoScheduling:
    @pytest.fixture
    def scheduling_setup(self, db, region, admin_user):
        cr = Resource(resource_type="classroom", name="Suggest Room", code="SUG-R1",
                     region_id=region.id, active=True)
        ins = Resource(resource_type="instructor", name="Suggest Teacher", code="SUG-T1",
                      region_id=region.id, active=True)
        db.session.add_all([cr, ins])
        db.session.commit()

        tomorrow = date.today() + timedelta(days=20)
        item = ScheduleItem(
            title="Suggest Test", region_id=region.id,
            scheduled_date=tomorrow, start_time=time(9, 0), end_time=time(11, 0),
            status="draft", created_by=admin_user.id, updated_by=admin_user.id,
        )
        db.session.add(item)
        db.session.commit()
        return item, cr, ins

    def test_suggest_returns_candidates(self, app, db, scheduling_setup):
        item, cr, ins = scheduling_setup
        suggestions = dispatch_service.suggest_assignments([item])
        assert len(suggestions) == 1
        assert len(suggestions[0]["candidates"]) > 0
        assert suggestions[0]["candidates"][0]["classroom_id"] == cr.id

    def test_suggest_does_not_commit(self, app, db, scheduling_setup):
        """Suggestions should not alter the item's status or assignment."""
        item, cr, ins = scheduling_setup
        dispatch_service.suggest_assignments([item])
        refreshed = db.session.get(ScheduleItem, item.id)
        assert refreshed.status == "draft"
        assert refreshed.classroom_id is None

    def test_confirm_suggestion_commits(self, app, db, admin_user, scheduling_setup):
        item, cr, ins = scheduling_setup
        dispatch_service.confirm_suggestion(item.id, cr.id, ins.id, admin_user.id)
        refreshed = db.session.get(ScheduleItem, item.id)
        assert refreshed.classroom_id == cr.id
        assert refreshed.instructor_id == ins.id
        assert refreshed.status in ("scheduled", "conflict")

    def test_confirm_creates_change_record(self, app, db, admin_user, scheduling_setup):
        item, cr, ins = scheduling_setup
        dispatch_service.confirm_suggestion(item.id, cr.id, ins.id, admin_user.id)
        from app.models.dispatch import ScheduleChange
        changes = ScheduleChange.query.filter_by(schedule_item_id=item.id).all()
        assert len(changes) >= 1
        assert changes[0].change_type == "semi_auto_assign"


# ── G. Search Facets ────────────────────────────────────────────────────────

class TestSearchFacets:
    @pytest.fixture
    def search_setup(self, db, admin_user, region):
        cat = Category(name="TestCat", slug="test-cat", active=True)
        db.session.add(cat)
        db.session.flush()

        item = cms_service.create_content(
            title="Facet Test Article", slug="facet-test",
            body_html="<p>Searchable content for facet testing</p>",
            summary="Facet test", author_id=admin_user.id,
            region_id=region.id, media_type="article",
            category_ids=[cat.id],
        )
        return item, cat

    def test_search_with_category_filter(self, app, db, admin_user, search_setup):
        item, cat = search_setup
        results, count = search_service.search(
            "facet", user_id=admin_user.id, category_id=cat.id)
        assert count >= 1
        assert any(r.record_type == "content" for r in results)

    def test_search_with_wrong_category_returns_none(self, app, db, admin_user, search_setup):
        item, cat = search_setup
        results, count = search_service.search(
            "facet", user_id=admin_user.id, category_id=99999)
        assert count == 0

    def test_search_with_media_type_filter(self, app, db, admin_user, search_setup):
        item, cat = search_setup
        results, count = search_service.search(
            "facet", user_id=admin_user.id, media_type="article")
        assert count >= 1
        assert all(r.media_type == "article" for r in results)

    def test_search_with_wrong_media_type_returns_none(self, app, db, admin_user, search_setup):
        item, cat = search_setup
        results, count = search_service.search(
            "facet", user_id=admin_user.id, media_type="video")
        assert count == 0

    def test_search_with_date_filter(self, app, db, admin_user, search_setup):
        results, count = search_service.search(
            "facet", user_id=admin_user.id,
            date_from=date(2020, 1, 1), date_to=date(2099, 12, 31))
        assert count >= 1

    def test_search_with_future_date_filter_excludes(self, app, db, admin_user, search_setup):
        results, count = search_service.search(
            "facet", user_id=admin_user.id,
            date_from=date(2099, 1, 1), date_to=date(2099, 12, 31))
        assert count == 0

    def test_search_logs_all_filters(self, app, db, admin_user, search_setup):
        item, cat = search_setup
        search_service.search(
            "facet", user_id=admin_user.id,
            record_type="content", region_id=1, media_type="article",
            category_id=cat.id)
        from app.models.search import SearchQuery
        logged = SearchQuery.query.filter_by(raw_query="facet").order_by(
            SearchQuery.id.desc()).first()
        assert logged is not None
        filters = json.loads(logged.filters_json)
        assert "category_id" in filters


# ── J. Analyst Seed Permissions ──────────────────────────────────────────────

class TestAnalystSeedPermissions:
    def test_analyst_lacks_order_management(self, app):
        """Analyst role should not have orders.manage permission."""
        from app.tasks.seed import ROLE_DEFINITIONS
        analyst_perms = ROLE_DEFINITIONS["analyst"]
        assert "orders.manage" not in analyst_perms
        assert "orders.record_payment" not in analyst_perms
        assert "orders.reconcile" not in analyst_perms

    def test_analyst_has_analytics_perms(self, app):
        from app.tasks.seed import ROLE_DEFINITIONS
        analyst_perms = ROLE_DEFINITIONS["analyst"]
        assert "analytics.view" in analyst_perms
        assert "analytics.export" in analyst_perms
        assert "analytics.view_financials" in analyst_perms
        assert "files.download" in analyst_perms


# ── K. Open Redirect Protection ─────────────────────────────────────────────

class TestOpenRedirect:
    def test_safe_relative_url(self):
        assert is_safe_redirect_url("/dashboard") is True
        assert is_safe_redirect_url("/admin/users") is True

    def test_reject_absolute_http(self):
        assert is_safe_redirect_url("http://evil.com") is False

    def test_reject_absolute_https(self):
        assert is_safe_redirect_url("https://evil.com/steal") is False

    def test_reject_protocol_relative(self):
        assert is_safe_redirect_url("//evil.com") is False

    def test_reject_javascript(self):
        assert is_safe_redirect_url("javascript:alert(1)") is False

    def test_reject_backslash(self):
        assert is_safe_redirect_url("/\\evil.com") is False

    def test_reject_empty(self):
        assert is_safe_redirect_url("") is False
        assert is_safe_redirect_url(None) is False

    def test_reject_no_leading_slash(self):
        assert is_safe_redirect_url("evil.com") is False

    def test_login_rejects_unsafe_next(self, client, admin_user):
        """Login should ignore unsafe next parameter."""
        resp = client.post("/login?next=http://evil.com", data={
            "username": "testadmin", "password": "adminpass123",
        }, follow_redirects=False)
        assert resp.status_code == 302
        assert "evil.com" not in resp.headers.get("Location", "")

    def test_login_allows_safe_next(self, client, admin_user):
        """Login should follow safe internal next parameter."""
        resp = client.post("/login?next=/admin/users", data={
            "username": "testadmin", "password": "adminpass123",
        }, follow_redirects=False)
        assert resp.status_code == 302
        assert "/admin/users" in resp.headers.get("Location", "")
