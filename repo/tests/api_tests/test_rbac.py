"""RBAC permission tests."""

import pytest


class TestPermissions:
    def test_admin_has_all_permissions(self, app, admin_user):
        with app.app_context():
            assert admin_user.has_permission("admin.manage_users")
            assert admin_user.has_permission("content.create")
            assert admin_user.has_permission("analytics.view_financials")

    def test_editor_limited_permissions(self, app, editor_user):
        with app.app_context():
            assert editor_user.has_permission("content.create")
            assert not editor_user.has_permission("admin.manage_users")
            assert not editor_user.has_permission("content.publish")

    def test_admin_page_requires_permission(self, client, logged_in_editor):
        resp = client.get("/admin/users", follow_redirects=True)
        assert b"Permission denied" in resp.data

    def test_multiple_roles(self, app, db, admin_user, editor_role):
        with app.app_context():
            admin_user.roles.append(editor_role)
            db.session.commit()
            perms = admin_user.get_permissions()
            assert "admin.manage_users" in perms
            assert "content.create" in perms
