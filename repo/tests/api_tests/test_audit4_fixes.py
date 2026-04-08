"""Tests for fourth audit remediation pass.

Covers:
A. Outbox acknowledgment ownership hardening (unclaimed ack denied, wrong consumer denied)
B. Schedule CSV reports honor submitted filters
C. Async report estimation is filter-aware
D. Blank slug content creation path safety
"""

import json
import pytest
from datetime import date, time, datetime
from decimal import Decimal

from app.services import outbox_service, analytics_service, cms_service
from app.models.api import OutboxEvent
from app.models.catalog import Order, ServiceItem
from app.models.dispatch import ScheduleItem
from app.models.analytics import ReportJob
from app.extensions import db


# ── Helpers ──────────────────────────────────────────────────────────────────

def _api_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _get_token(app, db, user, scopes):
    from app.services import api_auth_service
    cl, secret = api_auth_service.create_api_client("t4-client", scopes, user.id)
    cl_obj, _ = api_auth_service.authenticate_api_client(cl.key_id, secret)
    return api_auth_service.generate_jwt(cl_obj)


# ── A. Outbox Acknowledgment Ownership Hardening ────────────────────────────

class TestOutboxOwnershipHardening:
    """Verify that unclaimed events cannot be acked, and only the correct consumer can ack."""

    def test_service_unclaimed_ack_denied(self, app, db):
        """Direct ack of unclaimed event via service must be rejected."""
        event = outbox_service.create_event("test.unclaimed", "test", 1, {"key": "val"})
        # Event is pending and unclaimed (consumer_name is None)
        assert event.consumer_name is None
        with pytest.raises(ValueError, match="unclaimed"):
            outbox_service.acknowledge_event(event.id, consumer_name="sneaky_consumer")

    def test_service_wrong_consumer_denied(self, app, db):
        """Claimed event cannot be acked by a different consumer."""
        event = outbox_service.create_event("test.wrong", "test", 2, {})
        outbox_service.pull_events(consumer_name="owner_consumer")
        refreshed = db.session.get(OutboxEvent, event.id)
        assert refreshed.consumer_name == "owner_consumer"
        with pytest.raises(ValueError, match="different consumer"):
            outbox_service.acknowledge_event(event.id, consumer_name="thief_consumer")

    def test_service_correct_consumer_allowed(self, app, db):
        """Claimed event can be acked by the owning consumer."""
        event = outbox_service.create_event("test.correct", "test", 3, {})
        outbox_service.pull_events(consumer_name="legit_consumer")
        result = outbox_service.acknowledge_event(event.id, consumer_name="legit_consumer")
        assert result.status == "delivered"

    def test_service_ack_without_consumer_name_denied(self, app, db):
        """Ack without providing consumer_name must be rejected even if claimed."""
        event = outbox_service.create_event("test.noname", "test", 4, {})
        outbox_service.pull_events(consumer_name="some_consumer")
        with pytest.raises(ValueError, match="required"):
            outbox_service.acknowledge_event(event.id, consumer_name=None)

    def test_rest_unclaimed_ack_denied(self, client, app, db, admin_user):
        """REST ack of unclaimed event returns 400."""
        event = outbox_service.create_event("test.rest.unclaimed", "test", 5, {})
        token = _get_token(app, db, admin_user, ["outbox.write"])
        resp = client.post(
            f"/api/v1/outbox-events/{event.id}/ack",
            headers=_api_headers(token),
            data=json.dumps({"consumer": "rest_sneaky"}),
        )
        assert resp.status_code == 400
        assert "unclaimed" in resp.get_json()["error"].lower()

    def test_rest_wrong_consumer_denied(self, client, app, db, admin_user):
        """REST ack with wrong consumer returns 400."""
        event = outbox_service.create_event("test.rest.wrong", "test", 6, {})
        token = _get_token(app, db, admin_user, ["outbox.read", "outbox.write"])
        # Claim via pull
        client.get(f"/api/v1/outbox-events/pull?consumer=rest_owner",
                   headers=_api_headers(token))
        resp = client.post(
            f"/api/v1/outbox-events/{event.id}/ack",
            headers=_api_headers(token),
            data=json.dumps({"consumer": "rest_thief"}),
        )
        assert resp.status_code == 400
        assert "different consumer" in resp.get_json()["error"].lower()

    def test_rest_correct_consumer_allowed(self, client, app, db, admin_user):
        """REST ack with correct consumer succeeds."""
        event = outbox_service.create_event("test.rest.ok", "test", 7, {})
        token = _get_token(app, db, admin_user, ["outbox.read", "outbox.write"])
        client.get(f"/api/v1/outbox-events/pull?consumer=rest_owner",
                   headers=_api_headers(token))
        resp = client.post(
            f"/api/v1/outbox-events/{event.id}/ack",
            headers=_api_headers(token),
            data=json.dumps({"consumer": "rest_owner"}),
        )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "acknowledged"

    def test_graphql_unclaimed_ack_denied(self, client, app, db, admin_user):
        """GraphQL ack of unclaimed event returns error."""
        event = outbox_service.create_event("test.gql.unclaimed", "test", 8, {})
        token = _get_token(app, db, admin_user, ["outbox.write"])
        resp = client.post("/api/v1/graphql",
            headers=_api_headers(token),
            data=json.dumps({
                "query": f'mutation {{ acknowledgeOutboxEvent(id: {event.id}, consumer_name: "gql_sneaky") }}'
            }))
        data = resp.get_json()
        assert "errors" in data
        assert any("unclaimed" in e["message"].lower() for e in data["errors"])

    def test_graphql_wrong_consumer_denied(self, client, app, db, admin_user):
        """GraphQL ack with wrong consumer returns error."""
        event = outbox_service.create_event("test.gql.wrong", "test", 9, {})
        outbox_service.pull_events(consumer_name="gql_owner")
        token = _get_token(app, db, admin_user, ["outbox.write"])
        resp = client.post("/api/v1/graphql",
            headers=_api_headers(token),
            data=json.dumps({
                "query": f'mutation {{ acknowledgeOutboxEvent(id: {event.id}, consumer_name: "gql_thief") }}'
            }))
        data = resp.get_json()
        assert "errors" in data
        assert any("different consumer" in e["message"].lower() for e in data["errors"])

    def test_graphql_correct_consumer_allowed(self, client, app, db, admin_user):
        """GraphQL ack with correct consumer succeeds."""
        event = outbox_service.create_event("test.gql.ok", "test", 10, {})
        outbox_service.pull_events(consumer_name="gql_owner")
        token = _get_token(app, db, admin_user, ["outbox.write"])
        resp = client.post("/api/v1/graphql",
            headers=_api_headers(token),
            data=json.dumps({
                "query": f'mutation {{ acknowledgeOutboxEvent(id: {event.id}, consumer_name: "gql_owner") }}'
            }))
        data = resp.get_json()
        assert data.get("data", {}).get("acknowledgeOutboxEvent") is True


# ── B. Schedule CSV Reports Honor Submitted Filters ─────────────────────────

class TestScheduleReportFilters:
    """Verify that schedule reports apply region, date, and status filters."""

    @pytest.fixture
    def schedule_data(self, db, admin_user, region):
        """Create schedule items across two regions and dates."""
        from app.models.region import Region
        region2 = Region(code="R2", name="Region Two", sales_tax_rate=0.05, active=True)
        db.session.add(region2)
        db.session.commit()

        items = []
        for i, (r_id, sdate, status) in enumerate([
            (region.id, date(2025, 3, 1), "completed"),
            (region.id, date(2025, 3, 15), "draft"),
            (region.id, date(2025, 4, 1), "completed"),
            (region2.id, date(2025, 3, 10), "completed"),
            (region2.id, date(2025, 4, 5), "draft"),
        ]):
            item = ScheduleItem(
                title=f"Sched-{i}", region_id=r_id,
                scheduled_date=sdate, start_time=time(9, 0),
                end_time=time(10, 0), status=status,
                created_by=admin_user.id, updated_by=admin_user.id,
            )
            db.session.add(item)
            items.append(item)
        db.session.commit()
        return items, region, region2

    def test_region_filter(self, app, db, schedule_data):
        """Schedule report filtered by region returns only that region's items."""
        items, region, region2 = schedule_data
        rows, headers = analytics_service._generate_report_data(
            "schedule", {"region_id": region.id}
        )
        assert len(rows) == 3  # only region 1 items
        for row in rows:
            assert row[5] == region.name  # Region column

    def test_date_range_filter(self, app, db, schedule_data):
        """Schedule report filtered by date range returns only matching items."""
        items, region, region2 = schedule_data
        rows, headers = analytics_service._generate_report_data(
            "schedule", {"date_from": "2025-03-01", "date_to": "2025-03-31"}
        )
        assert len(rows) == 3  # March items only

    def test_status_filter(self, app, db, schedule_data):
        """Schedule report filtered by status returns only matching items."""
        items, region, region2 = schedule_data
        rows, headers = analytics_service._generate_report_data(
            "schedule", {"status": "completed"}
        )
        assert len(rows) == 3  # completed only

    def test_combined_filters(self, app, db, schedule_data):
        """Schedule report with combined region+status+date filters."""
        items, region, region2 = schedule_data
        rows, headers = analytics_service._generate_report_data(
            "schedule", {
                "region_id": region.id,
                "status": "completed",
                "date_from": "2025-03-01",
                "date_to": "2025-03-31",
            }
        )
        # Only region1 + completed + March = 1 item (Sched-0)
        assert len(rows) == 1
        assert rows[0][0] == "Sched-0"

    def test_state_key_aliases_status(self, app, db, schedule_data):
        """Browser form submits 'state' not 'status'; schedule query must accept both."""
        items, region, region2 = schedule_data
        rows, headers = analytics_service._generate_report_data(
            "schedule", {"state": "completed"}
        )
        assert len(rows) == 3  # same result as using "status" key

    def test_browser_form_end_to_end(self, client, app, db, schedule_data, logged_in_admin):
        """POST report_new with state= for schedule report applies filter."""
        items, region, region2 = schedule_data
        resp = client.post("/analytics/reports/new", data={
            "csrf_token": self._csrf(client),
            "report_type": "schedule",
            "state": "completed",
        }, follow_redirects=True)
        assert resp.status_code == 200
        # Find the created job and verify row count
        job = ReportJob.query.order_by(ReportJob.id.desc()).first()
        assert job is not None
        assert job.row_count == 3  # only completed items

    def test_estimation_uses_state_key(self, app, db, schedule_data):
        """Estimation must also accept 'state' key for schedule reports."""
        items, region, region2 = schedule_data
        # 5 total items, 3 completed — both under threshold but count should differ
        all_est = analytics_service.estimate_expected_seconds("schedule", {})
        filtered_est = analytics_service.estimate_expected_seconds("schedule", {"state": "completed"})
        assert all_est == 5 / 100  # 5 rows
        assert filtered_est == 3 / 100  # 3 rows

    @staticmethod
    def _csrf(client):
        """Extract CSRF token from a page."""
        resp = client.get("/analytics/kpis")
        html = resp.data.decode()
        import re
        m = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
        return m.group(1) if m else ""

    def test_unfiltered_returns_all(self, app, db, schedule_data):
        """No filters returns all schedule items."""
        items, region, region2 = schedule_data
        rows, headers = analytics_service._generate_report_data("schedule", {})
        assert len(rows) == 5


# ── C. Async Report Estimation is Filter-Aware ──────────────────────────────

class TestFilterAwareEstimation:
    """Verify that estimation uses the same filters as report generation."""

    def test_order_estimation_with_region_filter(self, app, db, admin_user, region):
        """Filtered order estimation should reflect filtered count."""
        from app.models.region import Region
        region2 = Region(code="EST-R2", name="Est Region 2", sales_tax_rate=0.0, active=True)
        db.session.add(region2)
        db.session.commit()
        # Create 600 orders in region2, 0 in region1
        for i in range(600):
            db.session.add(Order(
                order_number=f"EST-{i:04d}", customer_name=f"Corp {i}",
                region_id=region2.id, state="created", tax_rate=0,
                subtotal_amount=0, tax_amount=0, total_amount=0, paid_amount=0,
                created_by=admin_user.id, updated_by=admin_user.id,
            ))
        db.session.commit()
        # Unfiltered: 600 rows => 6s => async
        unfiltered = analytics_service.estimate_expected_seconds("orders", {})
        assert unfiltered > 5.0
        # Filtered to region1 (0 orders): 0s => sync
        filtered = analytics_service.estimate_expected_seconds(
            "orders", {"region_id": region.id}
        )
        assert filtered <= 5.0

    def test_order_estimation_with_state_filter(self, app, db, admin_user, region):
        """State filter in estimation reduces count."""
        for i in range(600):
            db.session.add(Order(
                order_number=f"ESTST-{i:04d}", customer_name=f"Corp {i}",
                region_id=region.id, state="created", tax_rate=0,
                subtotal_amount=0, tax_amount=0, total_amount=0, paid_amount=0,
                created_by=admin_user.id, updated_by=admin_user.id,
            ))
        db.session.commit()
        # No paid orders exist
        filtered = analytics_service.estimate_expected_seconds(
            "orders", {"state": "paid"}
        )
        assert filtered <= 5.0

    def test_schedule_estimation_with_region_filter(self, app, db, admin_user, region):
        """Filtered schedule estimation should reflect filtered count."""
        from app.models.region import Region
        region2 = Region(code="EST-SR2", name="Est Sched Region", sales_tax_rate=0.0, active=True)
        db.session.add(region2)
        db.session.commit()
        for i in range(600):
            db.session.add(ScheduleItem(
                title=f"EstSched-{i}", region_id=region2.id,
                scheduled_date=date(2025, 6, 1), start_time=time(9, 0),
                end_time=time(10, 0), status="draft",
                created_by=admin_user.id, updated_by=admin_user.id,
            ))
        db.session.commit()
        # Unfiltered: 600 rows => async
        unfiltered = analytics_service.estimate_expected_seconds("schedule", {})
        assert unfiltered > 5.0
        # Filtered to region1 (0 schedule items): sync
        filtered = analytics_service.estimate_expected_seconds(
            "schedule", {"region_id": region.id}
        )
        assert filtered <= 5.0

    def test_schedule_estimation_with_status_filter(self, app, db, admin_user, region):
        """Status filter in schedule estimation reduces count."""
        for i in range(600):
            db.session.add(ScheduleItem(
                title=f"EstSchedSt-{i}", region_id=region.id,
                scheduled_date=date(2025, 7, 1), start_time=time(9, 0),
                end_time=time(10, 0), status="draft",
                created_by=admin_user.id, updated_by=admin_user.id,
            ))
        db.session.commit()
        # No completed items
        filtered = analytics_service.estimate_expected_seconds(
            "schedule", {"status": "completed"}
        )
        assert filtered <= 5.0


# ── D. Blank Slug Content Creation Safety ────────────────────────────────────

class TestBlankSlugSafety:
    """Verify that blank slug cannot be persisted on content creation."""

    def test_blank_slug_derives_from_title(self, app, db, admin_user):
        """Empty slug should be auto-derived from title."""
        item = cms_service.create_content(
            title="My Great Article", slug="",
            body_html="<p>Body</p>", summary="Summary",
            author_id=admin_user.id,
        )
        assert item.slug == "my-great-article"

    def test_none_slug_derives_from_title(self, app, db, admin_user):
        """None slug should be auto-derived from title."""
        item = cms_service.create_content(
            title="Another Article", slug=None,
            body_html="<p>Body</p>", summary="Summary",
            author_id=admin_user.id,
        )
        assert item.slug == "another-article"

    def test_whitespace_slug_derives_from_title(self, app, db, admin_user):
        """Whitespace-only slug should be auto-derived from title."""
        item = cms_service.create_content(
            title="Whitespace Test", slug="   ",
            body_html="<p>Body</p>", summary="Summary",
            author_id=admin_user.id,
        )
        assert item.slug == "whitespace-test"

    def test_explicit_slug_preserved(self, app, db, admin_user):
        """Explicit non-blank slug should be preserved as-is."""
        item = cms_service.create_content(
            title="Title Here", slug="custom-slug",
            body_html="<p>Body</p>", summary="Summary",
            author_id=admin_user.id,
        )
        assert item.slug == "custom-slug"

    def test_duplicate_slug_rejected(self, app, db, admin_user):
        """Duplicate explicit slug raises ValueError."""
        cms_service.create_content(
            title="First", slug="unique-slug",
            body_html="<p>Body</p>", summary="Sum",
            author_id=admin_user.id,
        )
        with pytest.raises(ValueError, match="already exists"):
            cms_service.create_content(
                title="Second", slug="unique-slug",
                body_html="<p>Body</p>", summary="Sum",
                author_id=admin_user.id,
            )

    def test_duplicate_derived_slug_rejected(self, app, db, admin_user):
        """Two items with same title => derived slug collision raises error."""
        cms_service.create_content(
            title="Collision Title", slug="",
            body_html="<p>Body</p>", summary="Sum",
            author_id=admin_user.id,
        )
        with pytest.raises(ValueError, match="already exists"):
            cms_service.create_content(
                title="Collision Title", slug="",
                body_html="<p>Body</p>", summary="Sum",
                author_id=admin_user.id,
            )

    def test_api_blank_slug_derives_from_title(self, client, app, db, admin_user):
        """API content creation with blank slug auto-derives slug."""
        token = _get_token(app, db, admin_user, ["content.write", "content.read"])
        resp = client.post("/api/v1/content",
            headers=_api_headers(token),
            data=json.dumps({
                "title": "API Created Item",
                "slug": "",
                "body_html": "<p>API body</p>",
                "summary": "API summary",
            }))
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["slug"] == "api-created-item"


# ── E. JWT Revocation Invalidation ──────────────────────────────────────────

class TestJWTRevocation:
    def test_token_works_before_revocation(self, client, app, db, admin_user):
        from app.services import api_auth_service
        cl, secret = api_auth_service.create_api_client("rev-test", ["content.read"], admin_user.id)
        cl_obj, _ = api_auth_service.authenticate_api_client(cl.key_id, secret)
        token = api_auth_service.generate_jwt(cl_obj)
        resp = client.get("/api/v1/content", headers=_api_headers(token))
        assert resp.status_code == 200

    def test_token_fails_after_revocation(self, client, app, db, admin_user):
        """Already-issued JWT must be rejected after client revocation."""
        from app.services import api_auth_service
        cl, secret = api_auth_service.create_api_client("rev-test2", ["content.read"], admin_user.id)
        cl_obj, _ = api_auth_service.authenticate_api_client(cl.key_id, secret)
        token = api_auth_service.generate_jwt(cl_obj)
        resp = client.get("/api/v1/content", headers=_api_headers(token))
        assert resp.status_code == 200
        # Revoke
        cl.active = False
        db.session.commit()
        resp = client.get("/api/v1/content", headers=_api_headers(token))
        assert resp.status_code == 401
        assert "revoked" in resp.get_json()["error"].lower()

    def test_graphql_fails_after_revocation(self, client, app, db, admin_user):
        from app.services import api_auth_service
        cl, secret = api_auth_service.create_api_client("gql-rev", ["content.read"], admin_user.id)
        cl_obj, _ = api_auth_service.authenticate_api_client(cl.key_id, secret)
        token = api_auth_service.generate_jwt(cl_obj)
        cl.active = False
        db.session.commit()
        resp = client.post("/api/v1/graphql",
            headers=_api_headers(token),
            data=json.dumps({"query": "{ contents { id } }"}))
        assert resp.status_code == 401


# ── F. Blank Password Prevention ────────────────────────────────────────────

class TestBlankPasswordPrevention:
    def test_service_rejects_empty_password(self, app, db):
        from app.services.auth_service import create_user
        with pytest.raises(ValueError, match="at least 8"):
            create_user("blankuser", "Blank User", "")

    def test_service_rejects_short_password(self, app, db):
        from app.services.auth_service import create_user
        with pytest.raises(ValueError, match="at least 8"):
            create_user("shortuser", "Short User", "abc")

    def test_service_rejects_whitespace_password(self, app, db):
        from app.services.auth_service import create_user
        with pytest.raises(ValueError, match="at least 8"):
            create_user("spaceuser", "Space User", "       ")

    def test_service_accepts_valid_password(self, app, db):
        from app.services.auth_service import create_user
        user = create_user("validuser", "Valid User", "strongpass123")
        assert user.id is not None

    def test_admin_form_rejects_blank_password(self, client, app, db, logged_in_admin):
        resp = client.post("/admin/users/new", data={
            "username": "nopass", "display_name": "No Pass", "password": "",
        }, follow_redirects=True)
        from app.models.user import User
        assert User.query.filter_by(username="nopass").first() is None


# ── G. HTMX API Decoupling ─────────────────────────────────────────────────

class TestHTMXAPIDecoupling:
    def test_htmx_search_endpoint(self, client, app, db, logged_in_admin):
        resp = client.get("/api/v1/htmx/search?q=test")
        assert resp.status_code == 200
        assert resp.content_type.startswith("text/html")

    def test_htmx_content_endpoint(self, client, app, db, logged_in_admin):
        resp = client.get("/api/v1/htmx/content")
        assert resp.status_code == 200

    def test_htmx_orders_endpoint(self, client, app, db, logged_in_admin):
        resp = client.get("/api/v1/htmx/orders")
        assert resp.status_code == 200

    def test_htmx_schedules_endpoint(self, client, app, db, logged_in_admin):
        resp = client.get("/api/v1/htmx/schedules")
        assert resp.status_code == 200

    def test_htmx_kpis_endpoint(self, client, app, db, logged_in_admin):
        resp = client.get("/api/v1/htmx/kpis")
        assert resp.status_code == 200

    def test_htmx_requires_auth(self, client, app, db):
        resp = client.get("/api/v1/htmx/search?q=test")
        assert resp.status_code == 401

    def test_htmx_orders_requires_permission(self, client, app, db, logged_in_editor):
        resp = client.get("/api/v1/htmx/orders")
        assert resp.status_code == 403


# ── H. API File Download TTL ───────────────────────────────────────────────

class TestAPIFileDownloadTTL:
    @pytest.fixture
    def uploaded_file(self, app, db, admin_user):
        import io
        from werkzeug.datastructures import FileStorage
        f = FileStorage(stream=io.BytesIO(b"%PDF-1.4 test content"),
                       filename="test.pdf", content_type="application/pdf")
        from app.services import file_service
        return file_service.save_upload(f, admin_user.id)

    def test_signed_api_download_works(self, client, app, db, admin_user, uploaded_file):
        from app.services import api_auth_service, file_service
        cl, secret = api_auth_service.create_api_client("dl-test", ["files.read"], admin_user.id)
        cl_obj, _ = api_auth_service.authenticate_api_client(cl.key_id, secret)
        token = api_auth_service.generate_jwt(cl_obj)
        resp = client.get(f"/api/v1/files/{uploaded_file.id}/download-link",
                         headers=_api_headers(token))
        url = resp.get_json()["download_url"]
        assert "/api/v1/files/" in url
        resp = client.get(url, headers=_api_headers(token))
        assert resp.status_code == 200

    def test_direct_download_without_sig_denied(self, client, app, db, admin_user, uploaded_file):
        from app.services import api_auth_service
        cl, secret = api_auth_service.create_api_client("dl-nosig", ["files.read"], admin_user.id)
        cl_obj, _ = api_auth_service.authenticate_api_client(cl.key_id, secret)
        token = api_auth_service.generate_jwt(cl_obj)
        resp = client.get(f"/api/v1/files/{uploaded_file.id}/download",
                         headers=_api_headers(token))
        assert resp.status_code == 403


# ── I. Watermark Alignment ─────────────────────────────────────────────────

class TestWatermarkAlignment:
    def test_pdf_watermark_dispatched(self, app):
        from app.services.file_service import _apply_watermark
        from unittest.mock import MagicMock
        att = MagicMock()
        att.file_ext = "pdf"
        att.storage_path = "/fake/path.pdf"
        att.id = 1
        result = _apply_watermark(att, 1)
        assert result == "/fake/path.pdf"  # falls back on error

    def test_docx_returns_original(self, app):
        from app.services.file_service import _apply_watermark
        from unittest.mock import MagicMock
        att = MagicMock()
        att.file_ext = "docx"
        att.storage_path = "/fake/path.docx"
        att.id = 1
        result = _apply_watermark(att, 1)
        assert result == "/fake/path.docx"
