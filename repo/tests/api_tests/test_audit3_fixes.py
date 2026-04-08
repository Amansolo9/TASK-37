"""Tests for third audit remediation pass (items A-I).

Covers: sensitive field encryption/masking, analyst least-privilege,
GraphQL outbox consumer ownership, CMS versions guard, reports pagination,
async trigger >5s policy, username-check guard.
"""

import json
import pytest
from decimal import Decimal
from datetime import datetime

from app.services import order_service, analytics_service, outbox_service
from app.models.catalog import ServiceItem, Order
from app.models.analytics import ReportJob
from app.models.api import OutboxEvent
from app.extensions import db
from app.utils.encryption import encrypt_value, decrypt_value, mask_value


# ── Helpers ──────────────────────────────────────────────────────────────────

def _api_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _get_token(app, db, user, scopes):
    from app.services import api_auth_service
    cl, secret = api_auth_service.create_api_client("t3-client", scopes, user.id)
    cl_obj, _ = api_auth_service.authenticate_api_client(cl.key_id, secret)
    return api_auth_service.generate_jwt(cl_obj)


# ── A. Sensitive Field Encryption & Masking ──────────────────────────────────

class TestSensitiveFieldEncryption:
    def test_device_identifier_encrypt_roundtrip(self, app):
        with app.app_context():
            plaintext = "DEVICE-ABC-12345"
            encrypted = encrypt_value(plaintext)
            assert encrypted != plaintext
            assert decrypt_value(encrypted) == plaintext

    def test_credit_history_encrypt_roundtrip(self, app):
        with app.app_context():
            plaintext = "Score: 750, Last checked: 2024-01-15"
            encrypted = encrypt_value(plaintext)
            assert encrypted != plaintext
            assert decrypt_value(encrypted) == plaintext

    def test_mask_device_identifier(self, app):
        with app.app_context():
            masked = mask_value("DEVICE-ABC-12345")
            assert masked.endswith("2345")
            assert masked.startswith("*")
            assert "DEVICE" not in masked

    def test_order_stores_encrypted_device_id(self, app, db, admin_user, region):
        svc = ServiceItem(code="SENS-001", name="Sens Svc", pricing_model="per_use",
                         unit_rate=Decimal("10.00"), taxable=False, active=True)
        db.session.add(svc)
        db.session.commit()
        order = order_service.create_order(
            "Sensitive Corp", region.id, admin_user.id,
            device_identifier="DEV-XYZ-999",
            credit_history="Excellent - 800",
            line_items=[{"service_item_id": svc.id, "quantity": 1}],
        )
        refreshed = db.session.get(Order, order.id)
        # Encrypted at rest
        assert refreshed.encrypted_device_identifier is not None
        assert refreshed.encrypted_device_identifier != "DEV-XYZ-999"
        assert refreshed.encrypted_credit_history is not None
        assert refreshed.encrypted_credit_history != "Excellent - 800"
        # Decrypt correctly
        assert order_service.get_decrypted_device_identifier(refreshed) == "DEV-XYZ-999"
        assert order_service.get_decrypted_credit_history(refreshed) == "Excellent - 800"

    def test_order_without_sensitive_fields(self, app, db, admin_user, region):
        svc = ServiceItem(code="NOSENS-001", name="No Sens", pricing_model="per_use",
                         unit_rate=Decimal("10.00"), taxable=False, active=True)
        db.session.add(svc)
        db.session.commit()
        order = order_service.create_order(
            "Normal Corp", region.id, admin_user.id,
            line_items=[{"service_item_id": svc.id, "quantity": 1}],
        )
        assert order.encrypted_device_identifier is None
        assert order.encrypted_credit_history is None

    def test_sensitive_fields_masked_in_api_serializer(self, client, app, db, admin_user, region):
        """API serializer should expose boolean flags, not raw values."""
        svc = ServiceItem(code="API-SENS", name="API Sens", pricing_model="per_use",
                         unit_rate=Decimal("10.00"), taxable=False, active=True)
        db.session.add(svc)
        db.session.commit()
        order = order_service.create_order(
            "API Test", region.id, admin_user.id,
            device_identifier="DEV-123",
            line_items=[{"service_item_id": svc.id, "quantity": 1}],
        )
        token = _get_token(app, db, admin_user, ["orders.read"])
        resp = client.get("/api/v1/orders", headers=_api_headers(token))
        data = resp.get_json()
        # Find our order
        our_order = next(o for o in data if o["id"] == order.id)
        assert our_order["has_device_identifier"] is True
        assert "DEV-123" not in json.dumps(our_order)  # raw value never exposed

    def test_order_detail_masks_for_unprivileged(self, client, app, db, admin_user, region, editor_role):
        """Editor without analytics.view_financials should not see decrypted values."""
        from app.models.user import User, Role, RolePermission
        from app.utils.auth_helpers import hash_password
        # Create user with orders.manage but no financials
        ops_role = Role(name="ops_test", description="Ops")
        db.session.add(ops_role)
        db.session.flush()
        for p in ["orders.manage"]:
            db.session.add(RolePermission(role_id=ops_role.id, permission=p))
        ops_user = User(username="ops_test", display_name="Ops", password_hash=hash_password("opspass"), is_active_user=True)
        ops_user.roles.append(ops_role)
        db.session.add(ops_user)
        db.session.commit()

        svc = ServiceItem(code="MASK-001", name="Mask Svc", pricing_model="per_use",
                         unit_rate=Decimal("10.00"), taxable=False, active=True)
        db.session.add(svc)
        db.session.commit()
        # Give ops_user region access by creating an order in the same region
        order_service.create_order(
            "Ops Own Order", region.id, ops_user.id,
            line_items=[{"service_item_id": svc.id, "quantity": 1}],
        )
        order = order_service.create_order(
            "Mask Corp", region.id, admin_user.id,
            device_identifier="SECRET-DEV",
            credit_history="Secret Credit Info",
            line_items=[{"service_item_id": svc.id, "quantity": 1}],
        )

        client.post("/login", data={"username": "ops_test", "password": "opspass"})
        resp = client.get(f"/orders/{order.id}")
        assert resp.status_code == 200
        assert b"SECRET-DEV" not in resp.data
        assert b"Secret Credit Info" not in resp.data


# ── B. Analyst Least Privilege ───────────────────────────────────────────────

class TestAnalystLeastPrivilege:
    @pytest.fixture
    def analyst_user(self, db):
        from app.models.user import User, Role, RolePermission
        from app.utils.auth_helpers import hash_password
        role = Role(name="analyst_test", description="Analyst")
        db.session.add(role)
        db.session.flush()
        for p in ["analytics.view", "analytics.export", "analytics.view_financials", "files.download"]:
            db.session.add(RolePermission(role_id=role.id, permission=p))
        user = User(username="analyst_test", display_name="Analyst",
                    password_hash=hash_password("analystpass"), is_active_user=True)
        user.roles.append(role)
        db.session.add(user)
        db.session.commit()
        return user

    def test_analyst_denied_orders_index(self, client, app, db, analyst_user):
        client.post("/login", data={"username": "analyst_test", "password": "analystpass"})
        resp = client.get("/orders", follow_redirects=True)
        assert b"Permission denied" in resp.data

    def test_analyst_denied_order_detail(self, client, app, db, analyst_user, admin_user, region):
        svc = ServiceItem(code="AN-ORD", name="An Ord", pricing_model="per_use",
                         unit_rate=Decimal("10.00"), taxable=False, active=True)
        db.session.add(svc)
        db.session.commit()
        order = order_service.create_order("Analyst Test", region.id, admin_user.id,
                                           line_items=[{"service_item_id": svc.id, "quantity": 1}])
        client.post("/login", data={"username": "analyst_test", "password": "analystpass"})
        resp = client.get(f"/orders/{order.id}", follow_redirects=True)
        assert b"Permission denied" in resp.data

    def test_analyst_denied_catalog_services(self, client, app, db, analyst_user):
        client.post("/login", data={"username": "analyst_test", "password": "analystpass"})
        resp = client.get("/catalog/services", follow_redirects=True)
        assert b"Permission denied" in resp.data

    def test_analyst_can_access_kpis(self, client, app, db, analyst_user):
        client.post("/login", data={"username": "analyst_test", "password": "analystpass"})
        resp = client.get("/analytics/kpis")
        assert resp.status_code == 200

    def test_operational_role_still_allowed_orders(self, client, app, db, logged_in_admin):
        resp = client.get("/orders")
        assert resp.status_code == 200

    def test_analyst_dashboard_hides_orders_card(self, client, app, db, analyst_user):
        """Dashboard Orders card should not be visible to analyst."""
        client.post("/login", data={"username": "analyst_test", "password": "analystpass"})
        resp = client.get("/dashboard")
        assert resp.status_code == 200
        # Orders card links should not appear
        assert b'href="/orders"' not in resp.data
        assert b'href="/catalog/services"' not in resp.data
        # But analytics should be visible
        assert b'href="/analytics/kpis"' in resp.data


# ── C. GraphQL Outbox Ack Consumer Ownership ─────────────────────────────────

class TestGraphQLOutboxConsumerOwnership:
    def test_graphql_ack_requires_consumer_name(self, client, app, db, admin_user):
        event = outbox_service.create_event("test.gql", "test", 1, {})
        outbox_service.pull_events(consumer_name="gql_test")
        token = _get_token(app, db, admin_user, ["outbox.write"])
        # Missing consumer_name should fail
        resp = client.post("/api/v1/graphql",
            headers=_api_headers(token),
            data=json.dumps({
                "query": f'mutation {{ acknowledgeOutboxEvent(id: {event.id}) }}'
            }))
        data = resp.get_json()
        assert "errors" in data

    def test_graphql_ack_wrong_consumer_denied(self, client, app, db, admin_user):
        event = outbox_service.create_event("test.gql2", "test", 1, {})
        outbox_service.pull_events(consumer_name="owner_consumer")
        token = _get_token(app, db, admin_user, ["outbox.write"])
        resp = client.post("/api/v1/graphql",
            headers=_api_headers(token),
            data=json.dumps({
                "query": f'mutation {{ acknowledgeOutboxEvent(id: {event.id}, consumer_name: "thief_consumer") }}'
            }))
        data = resp.get_json()
        assert "errors" in data
        assert any("different consumer" in e["message"].lower() for e in data["errors"])

    def test_graphql_ack_correct_consumer_succeeds(self, client, app, db, admin_user):
        event = outbox_service.create_event("test.gql3", "test", 1, {})
        outbox_service.pull_events(consumer_name="valid_consumer")
        token = _get_token(app, db, admin_user, ["outbox.write"])
        resp = client.post("/api/v1/graphql",
            headers=_api_headers(token),
            data=json.dumps({
                "query": f'mutation {{ acknowledgeOutboxEvent(id: {event.id}, consumer_name: "valid_consumer") }}'
            }))
        data = resp.get_json()
        assert data.get("data", {}).get("acknowledgeOutboxEvent") is True


# ── D. CMS Version History Permission Guard ──────────────────────────────────

class TestCMSVersionsGuard:
    @pytest.fixture
    def content_with_version(self, db, admin_user, region):
        from app.services import cms_service
        item = cms_service.create_content(
            title="Version Test", slug="version-test-guard",
            body_html="<p>Test</p>", summary="test",
            author_id=admin_user.id, region_id=region.id,
        )
        return item

    def test_login_only_user_denied(self, client, app, db, content_with_version):
        """A user with no content permissions should be denied."""
        from app.models.user import User, Role, RolePermission
        from app.utils.auth_helpers import hash_password
        basic_role = Role(name="basic_test", description="Basic")
        db.session.add(basic_role)
        db.session.flush()
        # No content permissions
        db.session.add(RolePermission(role_id=basic_role.id, permission="files.download"))
        basic_user = User(username="basic_test", display_name="Basic",
                         password_hash=hash_password("basicpass"), is_active_user=True)
        basic_user.roles.append(basic_role)
        db.session.add(basic_user)
        db.session.commit()

        client.post("/login", data={"username": "basic_test", "password": "basicpass"})
        resp = client.get(f"/cms/content/{content_with_version.id}/versions", follow_redirects=True)
        assert b"Permission denied" in resp.data

    def test_content_role_allowed(self, client, app, db, logged_in_admin, content_with_version):
        """Admin (has content permissions) should access versions."""
        resp = client.get(f"/cms/content/{content_with_version.id}/versions")
        assert resp.status_code == 200
        assert b"Version" in resp.data


# ── E. Reports Pagination ───────────────────────────────────────────────────

class TestReportsPagination:
    def test_reports_list_paginated(self, client, app, db, logged_in_admin):
        resp = client.get("/analytics/reports")
        assert resp.status_code == 200

    def test_reports_page_parameter(self, client, app, db, logged_in_admin):
        resp = client.get("/analytics/reports?page=1")
        assert resp.status_code == 200

    def test_reports_default_page_size_50(self, app, db, admin_user):
        """Default pagination should be 50 items per page."""
        from app.utils.pagination import paginate_query
        # Verify the paginate_query defaults
        query = ReportJob.query
        with app.test_request_context("/?page=1"):
            result = paginate_query(query)
            assert result.per_page == 50


# ── F. Async Trigger >5s Policy ─────────────────────────────────────────────

class TestAsyncTriggerPolicy:
    def test_small_dataset_runs_sync(self, app, db, admin_user):
        """Few rows => expected < 5s => should run synchronously."""
        job = analytics_service.create_report_job("orders", {}, admin_user.id)
        refreshed = db.session.get(ReportJob, job.id)
        # With 0 rows, expected time is 0s, so it runs sync and completes
        assert refreshed.status in ("completed", "failed")

    def test_estimate_seconds_small_dataset(self, app, db):
        """Small row count should estimate < 5 seconds."""
        expected = analytics_service.estimate_expected_seconds("orders", {})
        assert expected <= 5.0  # 0 or few rows

    def test_estimate_seconds_scales_with_rows(self, app, db, admin_user, region):
        """Adding rows should increase estimated seconds."""
        svc = ServiceItem(code="ASYNC-001", name="Async Svc", pricing_model="per_use",
                         unit_rate=Decimal("10.00"), taxable=False, active=True)
        db.session.add(svc)
        db.session.commit()
        # Create many orders to push estimate above threshold
        for i in range(600):
            order = Order(
                order_number=f"ASYNC-{i:04d}", customer_name=f"Corp {i}",
                region_id=region.id, state="created", tax_rate=0,
                subtotal_amount=0, tax_amount=0, total_amount=0, paid_amount=0,
                created_by=admin_user.id, updated_by=admin_user.id,
            )
            db.session.add(order)
        db.session.commit()
        expected = analytics_service.estimate_expected_seconds("orders", {})
        assert expected > 5.0  # 600 rows / 100 per sec = 6 seconds

    def test_large_dataset_stays_queued(self, app, db, admin_user, region):
        """Many rows => expected > 5s => should stay queued (async)."""
        svc = ServiceItem(code="ASYNC-002", name="Async Svc2", pricing_model="per_use",
                         unit_rate=Decimal("10.00"), taxable=False, active=True)
        db.session.add(svc)
        db.session.commit()
        for i in range(600):
            order = Order(
                order_number=f"BIGRPT-{i:04d}", customer_name=f"Big Corp {i}",
                region_id=region.id, state="created", tax_rate=0,
                subtotal_amount=0, tax_amount=0, total_amount=0, paid_amount=0,
                created_by=admin_user.id, updated_by=admin_user.id,
            )
            db.session.add(order)
        db.session.commit()
        job = analytics_service.create_report_job("orders", {}, admin_user.id)
        refreshed = db.session.get(ReportJob, job.id)
        assert refreshed.status == "queued"  # async, not processed inline


# ── I. Username Check Admin Guard ────────────────────────────────────────────

class TestUsernameCheckGuard:
    def test_admin_allowed(self, client, app, db, logged_in_admin):
        resp = client.get("/admin/users/check-username?username=testadmin")
        assert resp.status_code == 200

    def test_non_admin_denied(self, client, app, db, logged_in_editor):
        resp = client.get("/admin/users/check-username?username=testadmin", follow_redirects=True)
        assert b"Permission denied" in resp.data
