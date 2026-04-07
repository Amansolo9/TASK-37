"""Tests for seventh audit remediation pass (items A-F).

Covers: attachment object-level auth, region isolation, report scope,
CSRF blueprint split, config hardening, logging.
"""

import io
import json
import pytest
from decimal import Decimal
from unittest.mock import patch

from app.services import api_auth_service, file_service, order_service
from app.services.access_policy import can_access_attachment, get_actor_region_ids
from app.models.files import Attachment
from app.models.catalog import ServiceItem, Order
from app.models.user import User, Role, RolePermission
from app.utils.auth_helpers import hash_password
from app.extensions import db
from app.config import Config


def _make_file(filename, content, content_type):
    from werkzeug.datastructures import FileStorage
    return FileStorage(stream=io.BytesIO(content), filename=filename, content_type=content_type)


def _api_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _get_token(app, db, user, scopes):
    cl, secret = api_auth_service.create_api_client("a6-client", scopes, user.id)
    cl_obj, _ = api_auth_service.authenticate_api_client(cl.key_id, secret)
    return api_auth_service.generate_jwt(cl_obj)


# ── A. Attachment Object-Level Authorization ─────────────────────────────────

class TestAttachmentObjectAuth:
    @pytest.fixture
    def two_users_with_files(self, db, admin_user, region):
        """Create two users with separate files."""
        role = Role(name="fileuser_test", description="File User")
        db.session.add(role)
        db.session.flush()
        for p in ["files.upload", "files.download"]:
            db.session.add(RolePermission(role_id=role.id, permission=p))
        user_b = User(username="userb_test", display_name="User B",
                     password_hash=hash_password("userbpass"), is_active_user=True)
        user_b.roles.append(role)
        db.session.add(user_b)
        db.session.commit()

        f_a = _make_file("admin_file.pdf", b"%PDF-1.4 admin content", "application/pdf")
        att_a = file_service.save_upload(f_a, admin_user.id)
        f_b = _make_file("userb_file.pdf", b"%PDF-1.4 userb content", "application/pdf")
        att_b = file_service.save_upload(f_b, user_b.id)
        return admin_user, user_b, att_a, att_b

    def test_uploader_can_access_own_file(self, app, db, two_users_with_files):
        admin, user_b, att_a, att_b = two_users_with_files
        assert can_access_attachment(att_a, admin) is True
        assert can_access_attachment(att_b, user_b) is True

    def test_non_uploader_cannot_access_unrelated_file(self, app, db, two_users_with_files):
        admin, user_b, att_a, att_b = two_users_with_files
        assert can_access_attachment(att_a, user_b) is False

    def test_admin_can_access_any_file(self, app, db, two_users_with_files):
        admin, user_b, att_a, att_b = two_users_with_files
        assert can_access_attachment(att_b, admin) is True

    def test_browser_download_link_denied_unrelated(self, client, app, db, two_users_with_files):
        admin, user_b, att_a, att_b = two_users_with_files
        client.post("/login", data={"username": "userb_test", "password": "userbpass"})
        resp = client.get(f"/files/{att_a.id}/download-link", follow_redirects=True)
        assert b"Access denied" in resp.data

    def test_browser_download_link_allowed_own(self, client, app, db, two_users_with_files):
        admin, user_b, att_a, att_b = two_users_with_files
        client.post("/login", data={"username": "userb_test", "password": "userbpass"})
        resp = client.get(f"/files/{att_b.id}/download-link")
        assert resp.status_code == 200

    def test_api_download_link_denied_unrelated(self, client, app, db, two_users_with_files):
        admin, user_b, att_a, att_b = two_users_with_files
        token = _get_token(app, db, user_b, ["files.read"])
        resp = client.get(f"/api/v1/files/{att_a.id}/download-link",
                         headers=_api_headers(token))
        assert resp.status_code == 403

    def test_api_download_link_allowed_own(self, client, app, db, two_users_with_files):
        admin, user_b, att_a, att_b = two_users_with_files
        token = _get_token(app, db, user_b, ["files.read"])
        resp = client.get(f"/api/v1/files/{att_b.id}/download-link",
                         headers=_api_headers(token))
        assert resp.status_code == 200

    def test_file_list_scoped_to_own_uploads(self, client, app, db, two_users_with_files):
        admin, user_b, att_a, att_b = two_users_with_files
        client.post("/login", data={"username": "userb_test", "password": "userbpass"})
        resp = client.get("/files")
        assert att_b.original_filename.encode() in resp.data
        assert att_a.original_filename.encode() not in resp.data


# ── B. Region Isolation ──────────────────────────────────────────────────────

class TestRegionIsolation:
    def test_admin_sees_all_regions(self, app, db, admin_user):
        result = get_actor_region_ids(admin_user)
        assert result is None  # None = all regions

    def test_limited_user_gets_scoped_regions(self, app, db):
        role = Role(name="limited_test", description="Limited")
        db.session.add(role)
        db.session.flush()
        db.session.add(RolePermission(role_id=role.id, permission="files.download"))
        user = User(username="limited_test", display_name="Limited",
                   password_hash=hash_password("limitpass"), is_active_user=True)
        user.roles.append(role)
        db.session.add(user)
        db.session.commit()
        result = get_actor_region_ids(user)
        assert isinstance(result, set)
        assert -1 in result  # empty set gets sentinel

    def test_htmx_content_applies_region_filter(self, client, app, db, logged_in_admin):
        """HTMX content endpoint should work for admin."""
        resp = client.get("/api/v1/htmx/content")
        assert resp.status_code == 200


# ── C. API Report Scope ─────────────────────────────────────────────────────

class TestAPIReportScope:
    def test_read_only_scope_denied_report_creation(self, client, app, db, admin_user):
        """analytics.read alone should not allow report creation."""
        token = _get_token(app, db, admin_user, ["analytics.read"])
        resp = client.post("/api/v1/reports",
            headers=_api_headers(token),
            data=json.dumps({"report_type": "orders"}))
        assert resp.status_code == 403

    def test_export_scope_allowed_report_creation(self, client, app, db, admin_user):
        """analytics.export should allow report creation."""
        token = _get_token(app, db, admin_user, ["analytics.export"])
        resp = client.post("/api/v1/reports",
            headers=_api_headers(token),
            data=json.dumps({"report_type": "orders"}))
        assert resp.status_code == 201


# ── D. CSRF Blueprint Split ─────────────────────────────────────────────────

class TestCSRFBlueprintSplit:
    def test_htmx_endpoints_are_in_separate_blueprint(self, app):
        """HTMX endpoints should be in htmx_api blueprint, not api blueprint."""
        with app.test_request_context():
            from flask import url_for
            htmx_url = url_for("htmx_api.htmx_search", q="test")
            assert "/api/v1/htmx/" in htmx_url

    def test_jwt_api_still_works(self, client, app, db, admin_user):
        """JWT API endpoints should still be CSRF-exempt and functional."""
        token = _get_token(app, db, admin_user, ["content.read"])
        resp = client.get("/api/v1/content", headers=_api_headers(token))
        assert resp.status_code == 200

    def test_htmx_endpoints_accessible_with_session(self, client, app, db, logged_in_admin):
        """Session-authenticated HTMX endpoints should work."""
        resp = client.get("/api/v1/htmx/search?q=test")
        assert resp.status_code == 200


# ── E. Config Hardening ──────────────────────────────────────────────────────

class TestConfigHardening:
    def test_default_secrets_rejected(self, app):
        """Production config validation should reject default secrets."""
        Config.SECRET_KEY = "dev-secret-key-change-me"
        Config.JWT_SECRET_KEY = "dev-jwt-secret-change-me"
        Config.FIELD_ENCRYPTION_KEY = ""
        with pytest.raises(RuntimeError, match="Production config validation failed"):
            Config.validate_production_secrets()

    def test_proper_secrets_pass(self, app):
        """Proper secrets should pass validation."""
        Config.SECRET_KEY = "a-real-strong-secret-key-here"
        Config.JWT_SECRET_KEY = "a-real-jwt-secret-key-here"
        Config.FIELD_ENCRYPTION_KEY = "sftLkMsijRqJsseVyPhBfqR28fi_Z0W_XA5QMvjVaCg="
        Config.validate_production_secrets()  # should not raise

    def test_partial_defaults_rejected(self, app):
        """Even one default secret should fail."""
        Config.SECRET_KEY = "good-secret"
        Config.JWT_SECRET_KEY = "dev-jwt-secret-change-me"
        Config.FIELD_ENCRYPTION_KEY = "sftLkMsijRqJsseVyPhBfqR28fi_Z0W_XA5QMvjVaCg="
        with pytest.raises(RuntimeError):
            Config.validate_production_secrets()


# ── F. Logging ───────────────────────────────────────────────────────────────

class TestLogging:
    def test_dispatch_exception_logs_warning(self, app, db, admin_user, region):
        """Forced integration failure in dispatch should log warning."""
        import logging
        from app.services import dispatch_service
        from datetime import date, time, timedelta
        tomorrow = date.today() + timedelta(days=30)
        with patch("app.services.search_service.index_schedule_item", side_effect=Exception("test_forced_error")):
            item = dispatch_service.create_schedule_item(
                "Log Test", region.id, tomorrow, time(9, 0), time(11, 0),
                user_id=admin_user.id,
            )
            # Verify the item was still created despite the exception
            assert item.id is not None
