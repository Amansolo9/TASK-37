"""REST API and JWT auth tests."""

import json
import pytest
from app.services import api_auth_service


class TestAPIAuth:
    def test_create_client_and_get_token(self, app, db, admin_user):
        with app.app_context():
            client_obj, secret = api_auth_service.create_api_client(
                "Test Client", ["content.read", "orders.read"], admin_user.id,
            )
            assert client_obj.key_id
            assert secret

            cl, err = api_auth_service.authenticate_api_client(client_obj.key_id, secret)
            assert cl is not None
            token = api_auth_service.generate_jwt(cl)
            assert token

            payload, err = api_auth_service.decode_jwt(token)
            assert payload is not None
            assert "content.read" in payload["scopes"]

    def test_quota_enforcement(self, app, db, admin_user):
        with app.app_context():
            client_obj, secret = api_auth_service.create_api_client(
                "Quota Test", ["content.read"], admin_user.id,
            )
            app.config["API_DAILY_QUOTA"] = 3
            for i in range(3):
                ok, count = api_auth_service.check_quota(client_obj.id)
                assert ok is True
            ok, count = api_auth_service.check_quota(client_obj.id)
            assert ok is False

    def test_api_requires_auth(self, client, db):
        resp = client.get("/api/v1/content")
        assert resp.status_code == 401

    def test_api_content_with_token(self, client, app, db, admin_user):
        with app.app_context():
            cl, secret = api_auth_service.create_api_client(
                "Token Test", ["content.read"], admin_user.id,
            )
            cl_obj, _ = api_auth_service.authenticate_api_client(cl.key_id, secret)
            token = api_auth_service.generate_jwt(cl_obj)
        resp = client.get("/api/v1/content", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
