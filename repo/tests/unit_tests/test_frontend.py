"""Frontend unit tests for server-rendered templates.

Verifies HTML structure, HTMX attribute contracts, CSRF protection,
role-based navigation rendering, form contracts, and JS asset inclusion.
"""

import pytest
from app.models.catalog import ServiceItem
from app.models.region import Region
from decimal import Decimal


# ── Navigation & Role-Based Rendering ───────────────────────────────────────

class TestNavigation:
    """Verify role-based navigation visibility in the base template."""

    def test_admin_sees_all_nav_sections(self, client, app, db, logged_in_admin):
        resp = client.get("/dashboard")
        html = resp.data.decode()
        assert "CMS" in html
        assert "Dispatch" in html
        assert "Orders" in html
        assert "Analytics" in html
        assert "Files" in html
        assert "Admin" in html

    def test_editor_sees_cms_and_files_only(self, client, app, db, logged_in_editor):
        resp = client.get("/dashboard")
        html = resp.data.decode()
        assert "CMS" in html
        assert "Files" in html
        # Editor should not see admin/orders/dispatch/analytics nav
        assert ">Admin<" not in html
        assert ">Orders<" not in html

    def test_nav_shows_user_display_name(self, client, app, db, logged_in_admin):
        resp = client.get("/dashboard")
        assert b"Test Admin" in resp.data

    def test_nav_has_logout_link(self, client, app, db, logged_in_admin):
        resp = client.get("/dashboard")
        assert b"Logout" in resp.data

    def test_unauthenticated_sees_no_nav(self, client, app, db):
        resp = client.get("/dashboard", follow_redirects=True)
        html = resp.data.decode()
        assert "navMain" not in html


# ── Dashboard Cards ─────────────────────────────────────────────────────────

class TestDashboardCards:
    """Verify role-based dashboard card rendering."""

    def test_admin_dashboard_shows_all_cards(self, client, app, db, logged_in_admin):
        resp = client.get("/dashboard")
        html = resp.data.decode()
        for title in ["CMS", "Dispatch", "Orders", "Search", "Analytics", "Files", "Admin"]:
            assert f'class="card-title">{title}</h5>' in html

    def test_editor_dashboard_hides_orders_card(self, client, app, db, logged_in_editor):
        resp = client.get("/dashboard")
        html = resp.data.decode()
        assert "CMS" in html
        assert '>Orders</h5>' not in html
        assert '>Admin</h5>' not in html

    def test_search_card_always_visible(self, client, app, db, logged_in_editor):
        resp = client.get("/dashboard")
        html = resp.data.decode()
        assert '>Search</h5>' in html


# ── HTMX Attribute Contracts ───────────────────────────────────────────────

class TestHTMXAttributes:
    """Verify HTMX attributes are correctly rendered on interactive elements."""

    def test_order_list_has_htmx_filter(self, client, app, db, logged_in_admin, region):
        resp = client.get("/orders")
        html = resp.data.decode()
        assert 'hx-get=' in html
        assert 'hx-target="#order-table"' in html
        assert 'hx-trigger="change"' in html
        assert 'name="state"' in html
        assert 'name="region_id"' in html

    def test_content_list_has_htmx_filter(self, client, app, db, logged_in_admin, region):
        resp = client.get("/cms/content")
        html = resp.data.decode()
        assert 'hx-get=' in html
        assert 'hx-target="#content-table"' in html
        assert 'hx-trigger="change"' in html

    def test_schedule_has_htmx_filter(self, client, app, db, logged_in_admin, region):
        resp = client.get("/dispatch/schedule")
        html = resp.data.decode()
        assert 'hx-get=' in html
        assert 'hx-target="#schedule-table"' in html
        assert 'hx-trigger="change"' in html

    def test_search_form_uses_htmx(self, client, app, db, logged_in_admin):
        resp = client.get("/search")
        html = resp.data.decode()
        assert 'hx-get=' in html
        assert 'hx-target="#search-results"' in html
        assert 'hx-trigger="submit"' in html

    def test_content_form_slug_check_htmx(self, client, app, db, logged_in_admin, region):
        resp = client.get("/cms/content/new")
        html = resp.data.decode()
        assert 'hx-get=' in html
        assert 'hx-trigger="keyup changed delay:500ms"' in html
        assert 'hx-target="#slug-check"' in html

    def test_htmx_partial_responses_are_html_fragments(self, client, app, db, logged_in_admin, region):
        resp = client.get("/api/v1/htmx/content")
        assert resp.status_code == 200
        html = resp.data.decode()
        # Partial should not contain <html> or <head> tags
        assert "<html" not in html
        assert "<head>" not in html


# ── CSRF Protection ─────────────────────────────────────────────────────────

class TestCSRFProtection:
    """Verify CSRF tokens are present in action forms that use explicit csrf_token()."""

    def test_schedule_actions_have_csrf(self, client, app, db, logged_in_admin, region):
        resp = client.get("/dispatch/schedule")
        html = resp.data.decode()
        # Auto-assign form uses explicit csrf_token() call
        assert 'name="csrf_token"' in html

    def test_content_edit_actions_have_csrf(self, client, app, db, logged_in_admin, region):
        from app.services import cms_service
        item = cms_service.create_content(
            title="CSRF Test", slug="csrf-test", body_html="<p>t</p>",
            summary="s", author_id=logged_in_admin.id, region_id=region.id)
        resp = client.get(f"/cms/content/{item.id}")
        html = resp.data.decode()
        # Submit-for-review form uses explicit csrf_token()
        assert 'name="csrf_token"' in html

    def test_forms_use_post_method(self, client, app, db, logged_in_admin, region):
        svc = ServiceItem(code="FE-SVC", name="FE Test", pricing_model="per_use",
                         unit_rate=Decimal("10.00"), taxable=False, active=True)
        db.session.add(svc)
        db.session.commit()
        resp = client.get("/orders/new")
        html = resp.data.decode()
        assert 'method="POST"' in html

    def test_login_form_uses_post(self, client, app, db):
        resp = client.get("/login")
        html = resp.data.decode()
        assert 'method="POST"' in html


# ── Form Structure ──────────────────────────────────────────────────────────

class TestFormStructure:
    """Verify form elements, inputs, and required attributes."""

    def test_login_form_structure(self, client, app, db):
        resp = client.get("/login")
        html = resp.data.decode()
        assert 'name="username"' in html
        assert 'name="password"' in html
        assert 'method="POST"' in html

    def test_order_form_has_line_items(self, client, app, db, logged_in_admin, region):
        svc = ServiceItem(code="FE-LI", name="Line Item Test", pricing_model="per_use",
                         unit_rate=Decimal("10.00"), taxable=False, active=True)
        db.session.add(svc)
        db.session.commit()
        resp = client.get("/orders/new")
        html = resp.data.decode()
        assert 'id="line-items"' in html
        assert 'name="line_svc_0"' in html
        assert 'name="line_qty_0"' in html
        assert 'min="1"' in html

    def test_content_form_has_editor(self, client, app, db, logged_in_admin, region):
        resp = client.get("/cms/content/new")
        html = resp.data.decode()
        assert 'id="editor"' in html
        assert 'name="body_html"' in html
        assert 'id="content-form"' in html

    def test_content_form_has_region_select(self, client, app, db, logged_in_admin, region):
        resp = client.get("/cms/content/new")
        html = resp.data.decode()
        assert 'name="region_id"' in html
        assert "Test Region" in html

    def test_search_form_has_all_filters(self, client, app, db, logged_in_admin):
        resp = client.get("/search")
        html = resp.data.decode()
        assert 'name="q"' in html
        assert 'name="type"' in html
        assert 'name="region_id"' in html
        assert 'name="category_id"' in html
        assert 'name="media_type"' in html
        assert 'name="date_from"' in html
        assert 'name="date_to"' in html


# ── JS Asset Inclusion ──────────────────────────────────────────────────────

class TestJSAssets:
    """Verify JavaScript libraries and inline scripts are included."""

    def test_base_includes_bootstrap_js(self, client, app, db, logged_in_admin):
        resp = client.get("/dashboard")
        html = resp.data.decode()
        assert "bootstrap.bundle.min.js" in html

    def test_base_includes_htmx(self, client, app, db, logged_in_admin):
        resp = client.get("/dashboard")
        html = resp.data.decode()
        assert "htmx.min.js" in html

    def test_content_form_includes_quill(self, client, app, db, logged_in_admin, region):
        resp = client.get("/cms/content/new")
        html = resp.data.decode()
        assert "quill.min.js" in html
        assert "quill.snow.css" in html
        assert "new Quill" in html

    def test_order_form_includes_add_line_script(self, client, app, db, logged_in_admin, region):
        svc = ServiceItem(code="FE-JS", name="JS Test", pricing_model="per_use",
                         unit_rate=Decimal("10.00"), taxable=False, active=True)
        db.session.add(svc)
        db.session.commit()
        resp = client.get("/orders/new")
        html = resp.data.decode()
        assert "addLine()" in html
        assert "lineIdx" in html

    def test_quill_syncs_to_hidden_input(self, client, app, db, logged_in_admin, region):
        resp = client.get("/cms/content/new")
        html = resp.data.decode()
        # JS should sync quill content to body_html input on form submit
        assert 'name="body_html"' in html
        assert 'quill.root.innerHTML' in html


# ── Content Workflow UI ─────────────────────────────────────────────────────

class TestContentWorkflowUI:
    """Verify content state-dependent action buttons render correctly."""

    @pytest.fixture
    def draft_content(self, db, logged_in_admin, region):
        from app.services import cms_service
        return cms_service.create_content(
            title="Draft Item", slug="draft-item",
            body_html="<p>draft</p>", summary="s",
            author_id=logged_in_admin.id, region_id=region.id)

    def test_draft_shows_submit_review_button(self, client, app, db, draft_content):
        resp = client.get(f"/cms/content/{draft_content.id}")
        html = resp.data.decode()
        assert "Submit for Review" in html

    def test_in_review_shows_publish_and_schedule(self, client, app, db, draft_content):
        from app.services import cms_service
        cms_service.submit_for_review(draft_content.id, draft_content.created_by)
        resp = client.get(f"/cms/content/{draft_content.id}")
        html = resp.data.decode()
        assert "Publish" in html
        assert "Schedule" in html

    def test_published_shows_withdraw(self, client, app, db, draft_content):
        from app.services import cms_service
        cms_service.submit_for_review(draft_content.id, draft_content.created_by)
        cms_service.approve_and_publish(draft_content.id, draft_content.created_by)
        resp = client.get(f"/cms/content/{draft_content.id}")
        html = resp.data.decode()
        assert "Withdraw" in html


# ── HTMX Partial Rendering ─────────────────────────────────────────────────

class TestHTMXPartials:
    """Verify HTMX partial endpoints return valid HTML fragments."""

    def test_htmx_content_partial(self, client, app, db, logged_in_admin, region):
        resp = client.get("/api/v1/htmx/content")
        assert resp.status_code == 200
        assert resp.content_type.startswith("text/html")

    def test_htmx_orders_partial(self, client, app, db, logged_in_admin, region):
        resp = client.get("/api/v1/htmx/orders")
        assert resp.status_code == 200
        assert resp.content_type.startswith("text/html")

    def test_htmx_schedules_partial(self, client, app, db, logged_in_admin, region):
        resp = client.get("/api/v1/htmx/schedules")
        assert resp.status_code == 200
        assert resp.content_type.startswith("text/html")

    def test_htmx_search_partial(self, client, app, db, logged_in_admin):
        resp = client.get("/api/v1/htmx/search?q=test")
        assert resp.status_code == 200
        assert resp.content_type.startswith("text/html")

    def test_htmx_kpis_partial(self, client, app, db, logged_in_admin):
        resp = client.get("/api/v1/htmx/kpis")
        assert resp.status_code == 200
        assert resp.content_type.startswith("text/html")

    def test_htmx_partials_require_auth(self, client, app, db):
        for path in ["/api/v1/htmx/content", "/api/v1/htmx/orders",
                     "/api/v1/htmx/schedules"]:
            resp = client.get(path)
            # Should redirect to login (302) or deny
            assert resp.status_code in (302, 401, 403)


# ── Static Assets Served ───────────────────────────────────────────────────

class TestStaticAssets:
    """Verify static vendor assets are accessible."""

    def test_bootstrap_css_served(self, client, app, db):
        resp = client.get("/static/vendor/bootstrap/css/bootstrap.min.css")
        assert resp.status_code == 200

    def test_htmx_js_served(self, client, app, db):
        resp = client.get("/static/vendor/htmx/htmx.min.js")
        assert resp.status_code == 200

    def test_app_css_served(self, client, app, db):
        resp = client.get("/static/css/app.css")
        assert resp.status_code == 200

    def test_bootstrap_js_served(self, client, app, db):
        resp = client.get("/static/vendor/bootstrap/js/bootstrap.bundle.min.js")
        assert resp.status_code == 200

    def test_quill_js_served(self, client, app, db):
        resp = client.get("/static/vendor/editor/quill.min.js")
        assert resp.status_code == 200
