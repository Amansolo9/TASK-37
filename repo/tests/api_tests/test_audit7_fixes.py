"""HTTP-level tests for previously uncovered API endpoints.

Covers all 23 API endpoints that lacked true no-mock HTTP test coverage:
  - POST /api/v1/auth/token
  - GET  /api/v1/content/<id>
  - POST /api/v1/content/<id>/submit-review
  - POST /api/v1/content/<id>/approve
  - POST /api/v1/content/<id>/schedule
  - POST /api/v1/content/<id>/withdraw
  - GET  /api/v1/search
  - GET  /api/v1/search/insights
  - GET  /api/v1/resources
  - POST /api/v1/resources
  - GET  /api/v1/schedules
  - POST /api/v1/schedules/auto-assign
  - GET  /api/v1/schedules/suggest
  - POST /api/v1/schedules/<id>/confirm-suggestion
  - POST /api/v1/schedules/<id>/reschedule
  - POST /api/v1/schedules/<id>/substitute
  - GET  /api/v1/service-items
  - POST /api/v1/orders/<id>/pay
  - POST /api/v1/orders/<id>/cancel
  - POST /api/v1/orders/<id>/complete
  - POST /api/v1/orders/<id>/refund
  - POST /api/v1/reconciliation-runs
  - GET  /api/v1/kpis
"""

import json
import pytest
from decimal import Decimal
from datetime import date, time, timedelta

from app.services import api_auth_service, cms_service, order_service, dispatch_service
from app.models.catalog import ServiceItem, Order
from app.models.dispatch import Resource, ScheduleItem
from app.models.region import Region


def _api_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _get_token(app, db, user, scopes):
    cl, secret = api_auth_service.create_api_client("a7-client", scopes, user.id)
    cl_obj, _ = api_auth_service.authenticate_api_client(cl.key_id, secret)
    return api_auth_service.generate_jwt(cl_obj)


# ── Auth Token ──────────────────────────────────────────────────────────────

class TestAuthToken:
    def test_token_success(self, client, app, db, admin_user):
        cl, secret = api_auth_service.create_api_client(
            "tok-test", ["content.read"], admin_user.id)
        resp = client.post("/api/v1/auth/token",
            headers={"Content-Type": "application/json"},
            data=json.dumps({"key_id": cl.key_id, "secret": secret}))
        assert resp.status_code == 200
        data = resp.get_json()
        assert "token" in data
        assert data["expires_in"] == 3600

    def test_token_bad_credentials(self, client, app, db, admin_user):
        resp = client.post("/api/v1/auth/token",
            headers={"Content-Type": "application/json"},
            data=json.dumps({"key_id": "bad", "secret": "bad"}))
        assert resp.status_code == 401
        assert "error" in resp.get_json()


# ── Content Detail & Lifecycle ──────────────────────────────────────────────

class TestContentDetailAPI:
    @pytest.fixture
    def content_item(self, app, db, admin_user, region):
        return cms_service.create_content(
            title="Detail Test", slug="detail-test",
            body_html="<p>body</p>", summary="sum",
            author_id=admin_user.id, region_id=region.id)

    def test_get_content_detail(self, client, app, db, admin_user, content_item):
        token = _get_token(app, db, admin_user, ["content.read"])
        resp = client.get(f"/api/v1/content/{content_item.id}",
                         headers=_api_headers(token))
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["id"] == content_item.id
        assert data["slug"] == "detail-test"

    def test_get_content_detail_not_found(self, client, app, db, admin_user):
        token = _get_token(app, db, admin_user, ["content.read"])
        resp = client.get("/api/v1/content/99999", headers=_api_headers(token))
        assert resp.status_code == 404

    def test_get_content_detail_wrong_scope(self, client, app, db, admin_user, content_item):
        token = _get_token(app, db, admin_user, ["orders.read"])
        resp = client.get(f"/api/v1/content/{content_item.id}",
                         headers=_api_headers(token))
        assert resp.status_code == 403

    def test_submit_review(self, client, app, db, admin_user, content_item):
        token = _get_token(app, db, admin_user, ["content.write"])
        resp = client.post(f"/api/v1/content/{content_item.id}/submit-review",
                          headers=_api_headers(token))
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "submitted"

    def test_submit_review_wrong_scope(self, client, app, db, admin_user, content_item):
        token = _get_token(app, db, admin_user, ["content.read"])
        resp = client.post(f"/api/v1/content/{content_item.id}/submit-review",
                          headers=_api_headers(token))
        assert resp.status_code == 403

    def test_approve_content(self, client, app, db, admin_user, content_item):
        cms_service.submit_for_review(content_item.id, admin_user.id)
        token = _get_token(app, db, admin_user, ["content.write"])
        resp = client.post(f"/api/v1/content/{content_item.id}/approve",
                          headers=_api_headers(token))
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "published"

    def test_schedule_content(self, client, app, db, admin_user, content_item):
        cms_service.submit_for_review(content_item.id, admin_user.id)
        token = _get_token(app, db, admin_user, ["content.write"])
        future = (date.today() + timedelta(days=7)).strftime("%m/%d/%Y %I:%M %p")
        resp = client.post(f"/api/v1/content/{content_item.id}/schedule",
                          headers=_api_headers(token),
                          data=json.dumps({"scheduled_at": future}))
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "scheduled"

    def test_withdraw_content(self, client, app, db, admin_user, content_item):
        cms_service.submit_for_review(content_item.id, admin_user.id)
        cms_service.approve_and_publish(content_item.id, admin_user.id)
        token = _get_token(app, db, admin_user, ["content.write"])
        resp = client.post(f"/api/v1/content/{content_item.id}/withdraw",
                          headers=_api_headers(token))
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "withdrawn"


# ── Search ──────────────────────────────────────────────────────────────────

class TestSearchAPI:
    def test_search_success(self, client, app, db, admin_user):
        token = _get_token(app, db, admin_user, ["search.read"])
        resp = client.get("/api/v1/search?q=test", headers=_api_headers(token))
        assert resp.status_code == 200
        data = resp.get_json()
        assert "results" in data
        assert "count" in data

    def test_search_missing_query(self, client, app, db, admin_user):
        token = _get_token(app, db, admin_user, ["search.read"])
        resp = client.get("/api/v1/search", headers=_api_headers(token))
        assert resp.status_code == 400

    def test_search_wrong_scope(self, client, app, db, admin_user):
        token = _get_token(app, db, admin_user, ["content.read"])
        resp = client.get("/api/v1/search?q=test", headers=_api_headers(token))
        assert resp.status_code == 403

    def test_search_insights(self, client, app, db, admin_user):
        token = _get_token(app, db, admin_user, ["search.read"])
        resp = client.get("/api/v1/search/insights", headers=_api_headers(token))
        assert resp.status_code == 200
        data = resp.get_json()
        assert "trending" in data
        assert "zero_results" in data

    def test_search_insights_wrong_scope(self, client, app, db, admin_user):
        token = _get_token(app, db, admin_user, ["orders.read"])
        resp = client.get("/api/v1/search/insights", headers=_api_headers(token))
        assert resp.status_code == 403


# ── Resources ───────────────────────────────────────────────────────────────

class TestResourcesAPI:
    def test_get_resources(self, client, app, db, admin_user, region):
        r = Resource(resource_type="classroom", name="Room A", code="RA",
                    region_id=region.id, active=True)
        db.session.add(r)
        db.session.commit()
        token = _get_token(app, db, admin_user, ["dispatch.read"])
        resp = client.get("/api/v1/resources", headers=_api_headers(token))
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) >= 1
        assert data[0]["name"] == "Room A"

    def test_get_resources_filtered_by_type(self, client, app, db, admin_user, region):
        db.session.add(Resource(resource_type="classroom", name="Room B", code="RB",
                               region_id=region.id, active=True))
        db.session.add(Resource(resource_type="instructor", name="Prof X", code="PX",
                               region_id=region.id, active=True))
        db.session.commit()
        token = _get_token(app, db, admin_user, ["dispatch.read"])
        resp = client.get("/api/v1/resources?type=instructor",
                         headers=_api_headers(token))
        assert resp.status_code == 200
        data = resp.get_json()
        assert all(r["type"] == "instructor" for r in data)

    def test_get_resources_wrong_scope(self, client, app, db, admin_user):
        token = _get_token(app, db, admin_user, ["content.read"])
        resp = client.get("/api/v1/resources", headers=_api_headers(token))
        assert resp.status_code == 403

    def test_create_resource(self, client, app, db, admin_user, region):
        token = _get_token(app, db, admin_user, ["dispatch.write"])
        resp = client.post("/api/v1/resources",
            headers=_api_headers(token),
            data=json.dumps({
                "resource_type": "classroom", "name": "New Room",
                "code": "NR", "region_id": region.id}))
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["name"] == "New Room"

    def test_create_resource_wrong_scope(self, client, app, db, admin_user, region):
        token = _get_token(app, db, admin_user, ["dispatch.read"])
        resp = client.post("/api/v1/resources",
            headers=_api_headers(token),
            data=json.dumps({
                "resource_type": "classroom", "name": "X", "code": "X"}))
        assert resp.status_code == 403


# ── Schedules ───────────────────────────────────────────────────────────────

class TestSchedulesAPI:
    @pytest.fixture
    def schedule_data(self, db, admin_user, region):
        tomorrow = date.today() + timedelta(days=1)
        classroom = Resource(resource_type="classroom", name="Room S",
                            code="RS", region_id=region.id, active=True)
        instructor = Resource(resource_type="instructor", name="Prof S",
                             code="PS", region_id=region.id, active=True)
        db.session.add_all([classroom, instructor])
        db.session.flush()
        item = dispatch_service.create_schedule_item(
            title="Sched Test", region_id=region.id,
            scheduled_date=tomorrow, start_time=time(9, 0),
            end_time=time(11, 0), user_id=admin_user.id)
        db.session.commit()
        return item, classroom, instructor, tomorrow

    def test_get_schedules(self, client, app, db, admin_user, schedule_data):
        token = _get_token(app, db, admin_user, ["dispatch.read"])
        resp = client.get("/api/v1/schedules", headers=_api_headers(token))
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_get_schedules_wrong_scope(self, client, app, db, admin_user):
        token = _get_token(app, db, admin_user, ["content.read"])
        resp = client.get("/api/v1/schedules", headers=_api_headers(token))
        assert resp.status_code == 403

    def test_auto_assign(self, client, app, db, admin_user, schedule_data):
        token = _get_token(app, db, admin_user, ["dispatch.write"])
        resp = client.post("/api/v1/schedules/auto-assign",
                          headers=_api_headers(token))
        assert resp.status_code == 200
        assert "results" in resp.get_json()

    def test_auto_assign_wrong_scope(self, client, app, db, admin_user):
        token = _get_token(app, db, admin_user, ["dispatch.read"])
        resp = client.post("/api/v1/schedules/auto-assign",
                          headers=_api_headers(token))
        assert resp.status_code == 403

    def test_suggest(self, client, app, db, admin_user, schedule_data):
        token = _get_token(app, db, admin_user, ["dispatch.read"])
        resp = client.get("/api/v1/schedules/suggest",
                         headers=_api_headers(token))
        assert resp.status_code == 200
        assert "suggestions" in resp.get_json()

    def test_confirm_suggestion(self, client, app, db, admin_user, schedule_data):
        item, classroom, instructor, _ = schedule_data
        token = _get_token(app, db, admin_user, ["dispatch.write"])
        resp = client.post(f"/api/v1/schedules/{item.id}/confirm-suggestion",
            headers=_api_headers(token),
            data=json.dumps({
                "classroom_id": classroom.id,
                "instructor_id": instructor.id}))
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["classroom_id"] == classroom.id

    def test_confirm_suggestion_wrong_scope(self, client, app, db, admin_user, schedule_data):
        item, classroom, instructor, _ = schedule_data
        token = _get_token(app, db, admin_user, ["dispatch.read"])
        resp = client.post(f"/api/v1/schedules/{item.id}/confirm-suggestion",
            headers=_api_headers(token),
            data=json.dumps({
                "classroom_id": classroom.id,
                "instructor_id": instructor.id}))
        assert resp.status_code == 403

    def test_reschedule(self, client, app, db, admin_user, schedule_data):
        item, classroom, instructor, _ = schedule_data
        token = _get_token(app, db, admin_user, ["dispatch.write"])
        new_date = (date.today() + timedelta(days=5)).strftime("%m/%d/%Y")
        resp = client.post(f"/api/v1/schedules/{item.id}/reschedule",
            headers=_api_headers(token),
            data=json.dumps({
                "new_date": new_date,
                "new_start": "14:00", "new_end": "16:00"}))
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["start"] == "14:00:00"

    def test_substitute(self, client, app, db, admin_user, schedule_data):
        item, classroom, instructor, _ = schedule_data
        # Assign classroom first
        dispatch_service.confirm_suggestion(
            item.id, classroom.id, instructor.id, admin_user.id)
        new_room = Resource(resource_type="classroom", name="Room S2",
                           code="RS2", region_id=item.region_id, active=True)
        db.session.add(new_room)
        db.session.commit()
        token = _get_token(app, db, admin_user, ["dispatch.write"])
        resp = client.post(f"/api/v1/schedules/{item.id}/substitute",
            headers=_api_headers(token),
            data=json.dumps({
                "resource_type": "classroom",
                "new_resource_id": new_room.id}))
        assert resp.status_code == 200
        assert resp.get_json()["classroom_id"] == new_room.id


# ── Service Items ───────────────────────────────────────────────────────────

class TestServiceItemsAPI:
    def test_get_service_items(self, client, app, db, admin_user):
        svc = ServiceItem(code="API-SI", name="API Svc", pricing_model="per_use",
                         unit_rate=Decimal("25.00"), taxable=False, active=True)
        db.session.add(svc)
        db.session.commit()
        token = _get_token(app, db, admin_user, ["orders.read"])
        resp = client.get("/api/v1/service-items", headers=_api_headers(token))
        assert resp.status_code == 200
        data = resp.get_json()
        assert any(s["code"] == "API-SI" for s in data)

    def test_get_service_items_wrong_scope(self, client, app, db, admin_user):
        token = _get_token(app, db, admin_user, ["content.read"])
        resp = client.get("/api/v1/service-items", headers=_api_headers(token))
        assert resp.status_code == 403


# ── Order Actions ───────────────────────────────────────────────────────────

class TestOrderActionsAPI:
    @pytest.fixture
    def order_with_svc(self, db, admin_user, region):
        svc = ServiceItem(code="ACT-SVC", name="Action Svc",
                         pricing_model="per_use", unit_rate=Decimal("50.00"),
                         taxable=True, active=True)
        db.session.add(svc)
        db.session.commit()
        order = order_service.create_order(
            "Action Corp", region.id, admin_user.id,
            line_items=[{"service_item_id": svc.id, "quantity": 1}])
        return order, svc

    def test_pay_order(self, client, app, db, admin_user, order_with_svc):
        order, svc = order_with_svc
        token = _get_token(app, db, admin_user, ["orders.write"])
        resp = client.post(f"/api/v1/orders/{order.id}/pay",
            headers=_api_headers(token),
            data=json.dumps({
                "tender_type": "cash",
                "receipt_number": "REC-001",
                "amount": str(order.total_amount)}))
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "paid"

    def test_pay_order_wrong_scope(self, client, app, db, admin_user, order_with_svc):
        order, _ = order_with_svc
        token = _get_token(app, db, admin_user, ["orders.read"])
        resp = client.post(f"/api/v1/orders/{order.id}/pay",
            headers=_api_headers(token),
            data=json.dumps({
                "tender_type": "cash", "receipt_number": "R",
                "amount": "50.00"}))
        assert resp.status_code == 403

    def test_cancel_order(self, client, app, db, admin_user, order_with_svc):
        order, _ = order_with_svc
        token = _get_token(app, db, admin_user, ["orders.write"])
        resp = client.post(f"/api/v1/orders/{order.id}/cancel",
                          headers=_api_headers(token))
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "canceled"

    def test_complete_order(self, client, app, db, admin_user, order_with_svc):
        order, _ = order_with_svc
        # Must pay first
        order_service.record_payment(
            order.id, "cash", "R-1", order.total_amount, admin_user.id)
        order_service.transition_order(order.id, "paid", admin_user.id)
        token = _get_token(app, db, admin_user, ["orders.write"])
        resp = client.post(f"/api/v1/orders/{order.id}/complete",
                          headers=_api_headers(token))
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "completed"

    def test_refund_order(self, client, app, db, admin_user, order_with_svc):
        order, _ = order_with_svc
        order_service.record_payment(
            order.id, "cash", "R-2", order.total_amount, admin_user.id)
        order_service.transition_order(order.id, "paid", admin_user.id)
        token = _get_token(app, db, admin_user, ["orders.write"])
        resp = client.post(f"/api/v1/orders/{order.id}/refund",
                          headers=_api_headers(token))
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "refunded"

    def test_cancel_wrong_scope(self, client, app, db, admin_user, order_with_svc):
        order, _ = order_with_svc
        token = _get_token(app, db, admin_user, ["orders.read"])
        resp = client.post(f"/api/v1/orders/{order.id}/cancel",
                          headers=_api_headers(token))
        assert resp.status_code == 403


# ── Reconciliation ──────────────────────────────────────────────────────────

class TestReconciliationAPI:
    def test_create_reconciliation_run(self, client, app, db, admin_user, region):
        svc = ServiceItem(code="REC-SVC", name="Recon Svc",
                         pricing_model="per_use", unit_rate=Decimal("30.00"),
                         taxable=False, active=True)
        db.session.add(svc)
        db.session.commit()
        order = order_service.create_order(
            "Recon Corp", region.id, admin_user.id,
            line_items=[{"service_item_id": svc.id, "quantity": 1}])
        order_service.record_payment(
            order.id, "cash", "RC-1", order.total_amount, admin_user.id)
        order_service.transition_order(order.id, "paid", admin_user.id)
        token = _get_token(app, db, admin_user, ["orders.write"])
        resp = client.post("/api/v1/reconciliation-runs",
            headers=_api_headers(token),
            data=json.dumps({
                "label": "April Run",
                "order_ids": [order.id],
                "actual_amounts": [str(order.total_amount)]}))
        assert resp.status_code == 201
        assert "id" in resp.get_json()

    def test_create_reconciliation_wrong_scope(self, client, app, db, admin_user):
        token = _get_token(app, db, admin_user, ["orders.read"])
        resp = client.post("/api/v1/reconciliation-runs",
            headers=_api_headers(token),
            data=json.dumps({
                "label": "X", "order_ids": [], "actual_amounts": []}))
        assert resp.status_code == 403


# ── KPIs ────────────────────────────────────────────────────────────────────

class TestKPIsAPI:
    def test_get_kpis(self, client, app, db, admin_user):
        token = _get_token(app, db, admin_user, ["analytics.read"])
        resp = client.get("/api/v1/kpis", headers=_api_headers(token))
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, dict)

    def test_get_kpis_with_scope(self, client, app, db, admin_user):
        token = _get_token(app, db, admin_user, ["analytics.read"])
        resp = client.get("/api/v1/kpis?scope=overview",
                         headers=_api_headers(token))
        assert resp.status_code == 200

    def test_get_kpis_wrong_scope(self, client, app, db, admin_user):
        token = _get_token(app, db, admin_user, ["content.read"])
        resp = client.get("/api/v1/kpis", headers=_api_headers(token))
        assert resp.status_code == 403

    def test_get_kpis_no_auth(self, client, app, db):
        resp = client.get("/api/v1/kpis")
        assert resp.status_code == 401
