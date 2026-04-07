"""CMS workflow tests."""

import pytest
from app.services import cms_service
from app.models.cms import ContentItem


class TestContentWorkflow:
    def test_create_content(self, app, db, admin_user, region):
        with app.app_context():
            item = cms_service.create_content(
                title="Test Article", slug="test-article",
                body_html="<p>Hello world</p>", summary="A test",
                author_id=admin_user.id, region_id=region.id,
            )
            assert item.id is not None
            assert item.workflow_state == "draft"
            assert item.current_version.title == "Test Article"

    def test_slug_uniqueness(self, app, db, admin_user, region):
        with app.app_context():
            cms_service.create_content("T1", "unique-slug", "<p>x</p>", "", admin_user.id)
            with pytest.raises(ValueError, match="already exists"):
                cms_service.create_content("T2", "unique-slug", "<p>y</p>", "", admin_user.id)

    def test_submit_for_review(self, app, db, admin_user, region):
        with app.app_context():
            item = cms_service.create_content("T", "submit-test", "<p>x</p>", "", admin_user.id)
            cms_service.submit_for_review(item.id, admin_user.id)
            refreshed = db.session.get(ContentItem, item.id)
            assert refreshed.workflow_state == "in_review"

    def test_approve_and_publish(self, app, db, admin_user, region):
        with app.app_context():
            item = cms_service.create_content("T", "pub-test", "<p>x</p>", "", admin_user.id)
            cms_service.submit_for_review(item.id, admin_user.id)
            cms_service.approve_and_publish(item.id, admin_user.id)
            refreshed = db.session.get(ContentItem, item.id)
            assert refreshed.workflow_state == "published"
            assert refreshed.published_version_id is not None

    def test_invalid_transition_raises(self, app, db, admin_user, region):
        with app.app_context():
            item = cms_service.create_content("T", "inv-test", "<p>x</p>", "", admin_user.id)
            with pytest.raises(ValueError):
                cms_service.approve_and_publish(item.id, admin_user.id)

    def test_withdraw(self, app, db, admin_user, region):
        with app.app_context():
            item = cms_service.create_content("T", "wd-test", "<p>x</p>", "", admin_user.id)
            cms_service.submit_for_review(item.id, admin_user.id)
            cms_service.approve_and_publish(item.id, admin_user.id)
            cms_service.withdraw_content(item.id, admin_user.id)
            refreshed = db.session.get(ContentItem, item.id)
            assert refreshed.workflow_state == "withdrawn"

    def test_html_sanitization(self, app, db, admin_user):
        with app.app_context():
            item = cms_service.create_content(
                "T", "san-test",
                '<p>Good</p><script>alert("bad")</script>',
                "", admin_user.id,
            )
            v = item.current_version
            assert "<script>" not in v.body_html
            assert "Good" in v.body_html

    def test_scheduled_publish(self, app, db, admin_user, region):
        from datetime import datetime, timedelta
        with app.app_context():
            item = cms_service.create_content("T", "sched-test", "<p>x</p>", "", admin_user.id)
            cms_service.submit_for_review(item.id, admin_user.id)
            future = datetime.utcnow() - timedelta(minutes=1)
            cms_service.schedule_publish(item.id, admin_user.id, future)
            count = cms_service.process_scheduled_publishes()
            assert count >= 1
            refreshed = db.session.get(ContentItem, item.id)
            assert refreshed.workflow_state == "published"


class TestCMSIntegration:
    def test_create_review_publish_flow(self, client, app, db, logged_in_admin, region):
        with app.app_context():
            resp = client.post("/cms/content/new", data={
                "title": "Integration Test", "slug": "integ-test",
                "body_html": "<p>Test body</p>", "summary": "Test",
                "region_id": region.id, "media_type": "article",
                "csrf_token": "",
            }, follow_redirects=True)
            assert resp.status_code == 200
