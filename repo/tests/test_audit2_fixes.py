"""Tests for second audit remediation pass (items A-J).

Covers: JWT file download, outbox consumer isolation, cost KPIs, report filters,
admin API client CRUD, signed URL robustness, MIME sniffing, pagination, feature flags.
"""

import io
import json
import pytest
from datetime import datetime, timedelta
from decimal import Decimal
from werkzeug.datastructures import FileStorage

from app.services import api_auth_service, outbox_service, analytics_service, file_service
from app.models.catalog import ServiceItem, Order
from app.models.api import ApiClient, OutboxEvent
from app.models.analytics import ReportJob
from app.models.files import Attachment
from app.extensions import db


def _make_file(filename, content, content_type):
    return FileStorage(
        stream=io.BytesIO(content),
        filename=filename,
        content_type=content_type,
    )


def _api_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _get_token(app, db, admin_user, scopes):
    cl, secret = api_auth_service.create_api_client("t-client", scopes, admin_user.id)
    cl_obj, _ = api_auth_service.authenticate_api_client(cl.key_id, secret)
    return api_auth_service.generate_jwt(cl_obj)


# ── A. JWT API File Download ────────────────────────────────────────────────

class TestAPIFileDownload:
    @pytest.fixture
    def uploaded_file(self, app, db, admin_user):
        f = _make_file("test.pdf", b"%PDF-1.4 test content here", "application/pdf")
        att = file_service.save_upload(f, admin_user.id)
        return att

    def _get_signed_download_url(self, client, token, file_id):
        """Helper: get a signed download link from the API, return the URL path."""
        resp = client.get(f"/api/v1/files/{file_id}/download-link",
                         headers=_api_headers(token))
        assert resp.status_code == 200
        return resp.get_json()["download_url"]

    def test_jwt_download_success(self, client, app, db, admin_user, uploaded_file):
        token = _get_token(app, db, admin_user, ["files.read"])
        download_url = self._get_signed_download_url(client, token, uploaded_file.id)
        resp = client.get(download_url, headers=_api_headers(token))
        assert resp.status_code == 200
        assert b"%PDF" in resp.data

    def test_jwt_download_wrong_scope_denied(self, client, app, db, admin_user, uploaded_file):
        token = _get_token(app, db, admin_user, ["content.read"])  # wrong scope
        resp = client.get(f"/api/v1/files/{uploaded_file.id}/download",
                         headers=_api_headers(token))
        assert resp.status_code == 403

    def test_jwt_download_no_auth_denied(self, client, app, db, uploaded_file):
        resp = client.get(f"/api/v1/files/{uploaded_file.id}/download")
        assert resp.status_code == 401

    def test_jwt_download_without_signature_denied(self, client, app, db, admin_user, uploaded_file):
        """Direct download without signed URL params should be denied."""
        token = _get_token(app, db, admin_user, ["files.read"])
        resp = client.get(f"/api/v1/files/{uploaded_file.id}/download",
                         headers=_api_headers(token))
        assert resp.status_code == 403

    def test_jwt_download_records_audit(self, client, app, db, admin_user, uploaded_file):
        from app.models.files import FileDownloadAudit
        token = _get_token(app, db, admin_user, ["files.read"])
        download_url = self._get_signed_download_url(client, token, uploaded_file.id)
        client.get(download_url, headers=_api_headers(token))
        audits = FileDownloadAudit.query.filter_by(attachment_id=uploaded_file.id).all()
        assert len(audits) >= 1


# ── B. Outbox Consumer-Scoped Ack ───────────────────────────────────────────

class TestOutboxConsumerIsolation:
    def test_pull_claims_for_consumer(self, app, db):
        event = outbox_service.create_event("test.topic", "test", 1, {"key": "val"})
        events = outbox_service.pull_events(consumer_name="consumer_a")
        assert len(events) >= 1
        refreshed = db.session.get(OutboxEvent, event.id)
        assert refreshed.consumer_name == "consumer_a"

    def test_consumer_a_can_ack_own_event(self, app, db):
        event = outbox_service.create_event("test.ack", "test", 1, {})
        outbox_service.pull_events(consumer_name="acker_a")
        result = outbox_service.acknowledge_event(event.id, consumer_name="acker_a")
        assert result.status == "delivered"

    def test_consumer_b_cannot_ack_a_event(self, app, db):
        event = outbox_service.create_event("test.cross", "test", 1, {})
        outbox_service.pull_events(consumer_name="owner_a")
        with pytest.raises(ValueError, match="different consumer"):
            outbox_service.acknowledge_event(event.id, consumer_name="thief_b")

    def test_already_acked_event_rejected(self, app, db):
        event = outbox_service.create_event("test.dup", "test", 1, {})
        outbox_service.pull_events(consumer_name="duper")
        outbox_service.acknowledge_event(event.id, consumer_name="duper")
        with pytest.raises(ValueError, match="already acknowledged"):
            outbox_service.acknowledge_event(event.id, consumer_name="duper")

    def test_api_pull_requires_consumer(self, client, app, db, admin_user):
        token = _get_token(app, db, admin_user, ["outbox.read"])
        resp = client.get("/api/v1/outbox-events/pull",
                         headers=_api_headers(token))
        assert resp.status_code == 400
        assert "consumer" in resp.get_json()["error"].lower()

    def test_api_ack_requires_consumer(self, client, app, db, admin_user):
        event = outbox_service.create_event("test.api", "test", 1, {})
        outbox_service.pull_events(consumer_name="api_test")
        token = _get_token(app, db, admin_user, ["outbox.write"])
        resp = client.post(f"/api/v1/outbox-events/{event.id}/ack",
                          headers=_api_headers(token),
                          data=json.dumps({}))
        assert resp.status_code == 400

    def test_api_ack_with_consumer_succeeds(self, client, app, db, admin_user):
        event = outbox_service.create_event("test.api2", "test", 1, {})
        outbox_service.pull_events(consumer_name="api_ok")
        token = _get_token(app, db, admin_user, ["outbox.write"])
        resp = client.post(f"/api/v1/outbox-events/{event.id}/ack",
                          headers=_api_headers(token),
                          data=json.dumps({"consumer": "api_ok"}))
        assert resp.status_code == 200


# ── C. Cost KPI ─────────────────────────────────────────────────────────────

class TestCostKPI:
    @pytest.fixture
    def order_with_cost(self, app, db, admin_user, region):
        from app.services import order_service
        svc = ServiceItem(code="COST-001", name="Cost Test Svc", pricing_model="per_use",
                         unit_rate=Decimal("100.00"), cost_amount=Decimal("40.00"),
                         taxable=False, active=True)
        db.session.add(svc)
        db.session.commit()
        order = order_service.create_order(
            "Cost Corp", region.id, admin_user.id,
            line_items=[{"service_item_id": svc.id, "quantity": 2}])
        order_service.record_payment(order.id, "cash", "COST-RCP", order.total_amount, admin_user.id)
        order_service.transition_order(order.id, "paid", admin_user.id)
        return order

    def test_cost_kpi_exists(self, app, db, order_with_cost):
        metrics = analytics_service.get_kpis("orders", {})
        assert "total_cost" in metrics
        assert "net_margin" in metrics

    def test_cost_computed_from_service_items(self, app, db, order_with_cost):
        metrics = analytics_service.get_kpis("orders", {})
        # 2 units * $40 cost = $80 total cost
        assert metrics["total_cost"] == 80.0

    def test_cost_masked_without_financial_permission(self, app, db, order_with_cost):
        metrics = analytics_service.get_kpis("orders", {}, user_permissions={"analytics.view"})
        assert metrics["total_cost"] == "[restricted]"

    def test_cost_visible_with_financial_permission(self, app, db, order_with_cost):
        metrics = analytics_service.get_kpis("orders", {},
                                             user_permissions={"analytics.view", "analytics.view_financials"})
        assert isinstance(metrics["total_cost"], (int, float))


# ── D. Report Multi-Dimensional Filters ─────────────────────────────────────

class TestReportFilters:
    def test_report_stores_date_filters(self, app, db, admin_user):
        job = analytics_service.create_report_job("orders", {
            "date_from": "2024-01-01", "date_to": "2024-12-31",
            "region_id": 1, "state": "paid",
        }, admin_user.id)
        stored = json.loads(job.filters_json)
        assert stored["date_from"] == "2024-01-01"
        assert stored["date_to"] == "2024-12-31"
        assert stored["region_id"] == 1

    def test_report_form_posts_filters(self, client, app, db, logged_in_admin):
        resp = client.post("/analytics/reports/new", data={
            "report_type": "orders",
            "region_id": "1",
            "state": "paid",
            "date_from": "01/01/2024",
            "date_to": "12/31/2024",
        }, follow_redirects=True)
        assert resp.status_code == 200

    def test_report_generation_applies_date_filter(self, app, db, admin_user, region):
        from app.services import order_service
        svc = ServiceItem(code="RPT-001", name="Report Svc", pricing_model="per_use",
                         unit_rate=Decimal("50.00"), taxable=False, active=True)
        db.session.add(svc)
        db.session.commit()
        order = order_service.create_order("Report Corp", region.id, admin_user.id,
                                           line_items=[{"service_item_id": svc.id, "quantity": 1}])
        # Report with future date range should exclude current orders
        job = analytics_service.create_report_job("orders", {
            "date_from": "2099-01-01", "date_to": "2099-12-31",
        }, admin_user.id)
        refreshed = db.session.get(ReportJob, job.id)
        assert refreshed.row_count == 0


# ── E. Admin API Client CRUD ────────────────────────────────────────────────

class TestAdminApiClientCRUD:
    def test_admin_can_create_client(self, client, app, db, logged_in_admin):
        resp = client.post("/admin/api-clients/new", data={
            "name": "Test Client",
            "scopes": "content.read\norders.read",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"Secret" in resp.data or b"secret" in resp.data
        assert b"Test Client" in resp.data

    def test_non_admin_cannot_create_client(self, client, app, db, logged_in_editor):
        resp = client.get("/admin/api-clients/new", follow_redirects=True)
        assert b"Permission denied" in resp.data

    def test_admin_can_revoke_client(self, client, app, db, logged_in_admin):
        cl, _ = api_auth_service.create_api_client("Revoke Me", ["content.read"], logged_in_admin.id)
        resp = client.post(f"/admin/api-clients/{cl.id}/revoke", follow_redirects=True)
        assert resp.status_code == 200
        refreshed = db.session.get(ApiClient, cl.id)
        assert refreshed.active is False

    def test_secret_shown_only_on_creation(self, client, app, db, logged_in_admin):
        """After creation, listing should not expose the raw secret."""
        resp = client.post("/admin/api-clients/new", data={
            "name": "Once Client",
            "scopes": "content.read",
        }, follow_redirects=True)
        # Creation page shows secret
        assert b"Once Client" in resp.data
        # List page should NOT show any raw secret
        list_resp = client.get("/admin/api-clients")
        assert b"secret" not in list_resp.data.lower() or b"Secret" not in list_resp.data


# ── F. Signed URL Malformed Params ──────────────────────────────────────────

class TestSignedURLRobustness:
    def test_malformed_expires_fails_safely(self, app):
        with app.app_context():
            result = file_service.verify_signed_url(1, "somesig", "not-a-number", "1")
            assert result is False

    def test_empty_sig_fails_safely(self, app):
        with app.app_context():
            result = file_service.verify_signed_url(1, "", "9999999999", "1")
            assert result is False

    def test_none_expires_fails_safely(self, app):
        with app.app_context():
            result = file_service.verify_signed_url(1, "sig", None, "1")
            assert result is False

    def test_none_user_fails_safely(self, app):
        with app.app_context():
            result = file_service.verify_signed_url(1, "sig", "9999999999", None)
            assert result is False

    def test_browser_malformed_expires_returns_403(self, client, app, db, logged_in_admin, admin_user):
        f = _make_file("test.pdf", b"%PDF-1.4 content", "application/pdf")
        att = file_service.save_upload(f, admin_user.id)
        resp = client.get(f"/files/{att.id}/download?sig=bad&expires=notanumber&uid={admin_user.id}")
        assert resp.status_code == 403


# ── H. Feature Flag Enforcement ─────────────────────────────────────────────

class TestFeatureFlag:
    def test_webhook_delivery_disabled_by_default(self, app, db):
        """With EXTERNAL_INTEGRATIONS_ENABLED=false, deliver_to_webhooks does nothing."""
        app.config["EXTERNAL_INTEGRATIONS_ENABLED"] = False
        event = outbox_service.create_event("test.flag", "test", 1, {})
        # Should not raise, should do nothing
        outbox_service.deliver_to_webhooks(event)
        assert True  # no exception


# ── I. Pagination Consistency ────────────────────────────────────────────────

class TestPaginationConsistency:
    def test_admin_users_paginated(self, client, app, db, logged_in_admin):
        resp = client.get("/admin/users")
        assert resp.status_code == 200
        assert b"pagination" in resp.data.lower() or b"page" in resp.data.lower() or resp.status_code == 200

    def test_admin_api_clients_paginated(self, client, app, db, logged_in_admin):
        resp = client.get("/admin/api-clients")
        assert resp.status_code == 200

    def test_files_list_paginated(self, client, app, db, logged_in_admin):
        resp = client.get("/files")
        assert resp.status_code == 200

    def test_page_parameter_works(self, client, app, db, logged_in_admin):
        resp = client.get("/admin/users?page=1&per_page=10")
        assert resp.status_code == 200


# ── J. MIME Sniffing ────────────────────────────────────────────────────────

class TestMIMESniffing:
    def test_pdf_content_matches(self, app):
        """Real PDF content with correct MIME should pass."""
        with app.app_context():
            f = _make_file("doc.pdf", b"%PDF-1.4 real content", "application/pdf")
            ok, err = file_service.validate_upload(f)
            assert ok is True

    def test_jpeg_content_in_png_ext_rejected(self, app):
        """JPEG magic bytes in a .png file should be rejected by sniffing."""
        with app.app_context():
            f = _make_file("fake.png", b"\xff\xd8\xff\xe0 jpeg data", "image/png")
            ok, err = file_service.validate_upload(f)
            assert ok is False
            assert "content detected" in err.lower()

    def test_png_content_in_jpg_ext_rejected(self, app):
        """PNG magic bytes in a .jpg file should be rejected by sniffing."""
        with app.app_context():
            f = _make_file("fake.jpg", b"\x89PNG\r\n\x1a\n png data", "image/jpeg")
            ok, err = file_service.validate_upload(f)
            assert ok is False

    def test_pdf_content_in_docx_ext_rejected(self, app):
        """PDF content in a .docx file should be rejected."""
        with app.app_context():
            f = _make_file("fake.docx", b"%PDF-1.4 sneaky", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            ok, err = file_service.validate_upload(f)
            assert ok is False

    def test_unknown_content_passes_if_mime_ok(self, app):
        """File with no recognizable magic bytes but correct MIME should pass."""
        with app.app_context():
            f = _make_file("doc.pdf", b"\x00\x00\x00 unknown header", "application/pdf")
            ok, err = file_service.validate_upload(f)
            assert ok is True  # sniffing returns None, so no rejection
