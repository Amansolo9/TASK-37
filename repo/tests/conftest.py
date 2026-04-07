"""Pytest fixtures for GreenCycle tests."""

import pytest
from app import create_app
from app.config import TestConfig
from app.extensions import db as _db
from app.models.user import User, Role, RolePermission
from app.utils.auth_helpers import hash_password


@pytest.fixture(scope="function")
def app():
    app = create_app(TestConfig)
    with app.app_context():
        _db.create_all()
        # Create FTS table
        try:
            _db.session.execute(_db.text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5("
                "title, body_text, tags_text, metadata_text, "
                "content='search_documents', content_rowid='id')"
            ))
            _db.session.commit()
        except Exception:
            pass
        yield app
        _db.session.remove()
        # Disable FK checks for clean teardown
        _db.session.execute(_db.text("PRAGMA foreign_keys=OFF"))
        _db.drop_all()
        _db.session.execute(_db.text("PRAGMA foreign_keys=ON"))


@pytest.fixture
def db(app):
    return _db


@pytest.fixture
def client(app, db):
    return app.test_client()


@pytest.fixture
def admin_role(db):
    role = Role(name="admin", description="Admin")
    db.session.add(role)
    db.session.flush()
    perms = [
        "admin.manage_users", "admin.manage_roles", "admin.manage_settings",
        "admin.manage_api_keys", "admin.view_audit_logs",
        "content.create", "content.edit", "content.submit_review", "content.review",
        "content.publish", "content.schedule", "content.withdraw",
        "content.manage_taxonomy", "content.manage_homepage_placement",
        "dispatch.manage_resources", "dispatch.manage_schedule",
        "dispatch.resolve_conflicts", "dispatch.view_change_notices",
        "orders.manage", "orders.record_payment", "orders.reconcile",
        "analytics.view", "analytics.export", "analytics.view_financials",
        "files.upload", "files.download", "files.manage_retention",
        "api.access",
    ]
    for p in perms:
        db.session.add(RolePermission(role_id=role.id, permission=p))
    db.session.commit()
    return role


@pytest.fixture
def editor_role(db):
    role = Role(name="editor", description="Editor")
    db.session.add(role)
    db.session.flush()
    for p in ["content.create", "content.edit", "content.submit_review",
              "content.manage_taxonomy", "files.upload", "files.download"]:
        db.session.add(RolePermission(role_id=role.id, permission=p))
    db.session.commit()
    return role


@pytest.fixture
def admin_user(db, admin_role):
    user = User(
        username="testadmin", display_name="Test Admin",
        password_hash=hash_password("adminpass123"),
        is_active_user=True,
    )
    user.roles.append(admin_role)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def editor_user(db, editor_role):
    user = User(
        username="testeditor", display_name="Test Editor",
        password_hash=hash_password("editorpass123"),
        is_active_user=True,
    )
    user.roles.append(editor_role)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def region(db):
    from app.models.region import Region
    r = Region(code="TEST", name="Test Region", sales_tax_rate=0.0825, active=True)
    db.session.add(r)
    db.session.commit()
    return r


@pytest.fixture
def logged_in_admin(client, admin_user):
    client.post("/login", data={
        "username": "testadmin", "password": "adminpass123",
    }, follow_redirects=True)
    return admin_user


@pytest.fixture
def logged_in_editor(client, editor_user):
    client.post("/login", data={
        "username": "testeditor", "password": "editorpass123",
    }, follow_redirects=True)
    return editor_user
