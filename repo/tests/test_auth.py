"""Authentication tests: login, lockout, timeout, password hashing."""

import pytest
from datetime import datetime, timedelta
from app.utils.auth_helpers import hash_password, verify_password
from app.services.auth_service import authenticate_user
from app.models.user import User
from app.extensions import db


class TestPasswordHashing:
    def test_hash_and_verify(self, app):
        with app.app_context():
            h = hash_password("secret123")
            assert verify_password(h, "secret123")
            assert not verify_password(h, "wrong")

    def test_hash_is_unique(self, app):
        with app.app_context():
            h1 = hash_password("same")
            h2 = hash_password("same")
            assert h1 != h2  # salted


class TestLoginLockout:
    def test_lockout_after_5_failures(self, app, db, admin_user):
        with app.app_context():
            for i in range(5):
                user, err = authenticate_user("testadmin", "wrongpass")
                assert user is None
            user = User.query.filter_by(username="testadmin").first()
            assert user.lockout_until is not None
            assert user.failed_login_attempts >= 5

    def test_login_blocked_during_lockout(self, app, db, admin_user):
        with app.app_context():
            for i in range(5):
                authenticate_user("testadmin", "wrongpass")
            user, err = authenticate_user("testadmin", "adminpass123")
            assert user is None
            assert "locked" in err.lower()

    def test_successful_login_resets_attempts(self, app, db, admin_user):
        with app.app_context():
            authenticate_user("testadmin", "wrongpass")
            authenticate_user("testadmin", "wrongpass")
            user, err = authenticate_user("testadmin", "adminpass123")
            assert user is not None
            assert user.failed_login_attempts == 0


class TestSessionTimeout:
    def test_idle_timeout_redirects(self, client, admin_user, db, app):
        with app.app_context():
            client.post("/login", data={
                "username": "testadmin", "password": "adminpass123",
            })
            user = User.query.filter_by(username="testadmin").first()
            user.last_activity_at = datetime.utcnow() - timedelta(minutes=31)
            db.session.commit()
            resp = client.get("/dashboard")
            assert resp.status_code == 302  # should redirect to login on timeout


class TestLoginLogout:
    def test_login_success(self, client, admin_user):
        resp = client.post("/login", data={
            "username": "testadmin", "password": "adminpass123",
        }, follow_redirects=True)
        assert resp.status_code == 200

    def test_login_invalid(self, client, admin_user):
        resp = client.post("/login", data={
            "username": "testadmin", "password": "wrong",
        }, follow_redirects=True)
        assert b"Invalid" in resp.data

    def test_logout(self, client, logged_in_admin):
        resp = client.get("/logout", follow_redirects=True)
        assert resp.status_code == 200
