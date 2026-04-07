"""REST API v1 routes with JWT auth and quota enforcement."""

import json
from functools import wraps
from flask import request, jsonify, g
from app.blueprints.api import bp
from app.services import api_auth_service, cms_service, order_service, dispatch_service
from app.services import search_service, analytics_service, file_service, outbox_service
from app.models.cms import ContentItem
from app.models.catalog import Order, ServiceItem
from app.models.dispatch import ScheduleItem, Resource
from app.models.analytics import ReportJob
from app.models.user import User
from pathlib import Path
from app.extensions import db, csrf
from app.utils.auth_context import get_current_actor_id
from app.services.access_policy import apply_region_filter, check_region_access


def jwt_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing or invalid Authorization header"}), 401
        token = auth_header[7:]
        payload, error = api_auth_service.decode_jwt(token)
        if error:
            return jsonify({"error": error}), 401

        # Verify the API client still exists and is active (handles revocation)
        from app.models.api import ApiClient
        client = db.session.get(ApiClient, payload["client_id"])
        if not client or not client.active:
            return jsonify({"error": "API client has been revoked or deactivated"}), 401

        ok, count = api_auth_service.check_quota(payload["client_id"])
        if not ok:
            return jsonify({"error": "Daily quota exceeded", "usage": count}), 429

        g.api_client_id = payload["client_id"]
        g.api_scopes = payload.get("scopes", [])
        return f(*args, **kwargs)
    return decorated


def scope_required(scope):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if scope not in g.get("api_scopes", []):
                return jsonify({"error": f"Scope '{scope}' required"}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator


# --- Auth ---
@bp.route("/auth/token", methods=["POST"])
def api_token():
    data = request.get_json(silent=True) or {}
    key_id = data.get("key_id", "")
    secret = data.get("secret", "")
    client, error = api_auth_service.authenticate_api_client(key_id, secret)
    if error:
        return jsonify({"error": error}), 401
    token = api_auth_service.generate_jwt(client)
    return jsonify({"token": token, "expires_in": 3600})


# --- Content ---
@bp.route("/content", methods=["GET"])
@jwt_required
@scope_required("content.read")
def api_content_list():
    state = request.args.get("state")
    query = cms_service.get_content_list(state=state)
    actor = db.session.get(User, get_current_actor_id())
    if actor:
        query = apply_region_filter(query, ContentItem, actor)
    items = query.limit(50).all()
    return jsonify([_serialize_content(i) for i in items])


@bp.route("/content/<int:id>", methods=["GET"])
@jwt_required
@scope_required("content.read")
def api_content_detail(id):
    item = db.session.get(ContentItem, id)
    if not item:
        return jsonify({"error": "Not found"}), 404
    actor = db.session.get(User, get_current_actor_id())
    if not actor or not check_region_access(item, actor):
        return jsonify({"error": "Access denied"}), 403
    return jsonify(_serialize_content(item))


@bp.route("/content", methods=["POST"])
@jwt_required
@scope_required("content.write")
def api_content_create():
    data = request.get_json(silent=True) or {}
    try:
        item = cms_service.create_content(
            title=data["title"], slug=data.get("slug", ""),
            body_html=data.get("body_html", ""), summary=data.get("summary", ""),
            author_id=get_current_actor_id(),
            region_id=data.get("region_id"), media_type=data.get("media_type"),
        )
        return jsonify(_serialize_content(item)), 201
    except (ValueError, KeyError) as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/content/<int:id>/submit-review", methods=["POST"])
@jwt_required
@scope_required("content.write")
def api_submit_review(id):
    item = db.session.get(ContentItem, id)
    if not item:
        return jsonify({"error": "Not found"}), 404
    actor = db.session.get(User, get_current_actor_id())
    if not actor or not check_region_access(item, actor):
        return jsonify({"error": "Access denied"}), 403
    try:
        cms_service.submit_for_review(id, user_id=get_current_actor_id())
        return jsonify({"status": "submitted"})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/content/<int:id>/approve", methods=["POST"])
@jwt_required
@scope_required("content.write")
def api_approve(id):
    item = db.session.get(ContentItem, id)
    if not item:
        return jsonify({"error": "Not found"}), 404
    actor = db.session.get(User, get_current_actor_id())
    if not actor or not check_region_access(item, actor):
        return jsonify({"error": "Access denied"}), 403
    try:
        cms_service.approve_and_publish(id, reviewer_id=get_current_actor_id())
        return jsonify({"status": "published"})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/content/<int:id>/schedule", methods=["POST"])
@jwt_required
@scope_required("content.write")
def api_schedule(id):
    item = db.session.get(ContentItem, id)
    if not item:
        return jsonify({"error": "Not found"}), 404
    actor = db.session.get(User, get_current_actor_id())
    if not actor or not check_region_access(item, actor):
        return jsonify({"error": "Access denied"}), 403
    data = request.get_json(silent=True) or {}
    from app.utils.date_helpers import parse_datetime_us
    scheduled_at = parse_datetime_us(data.get("scheduled_at"))
    if not scheduled_at:
        return jsonify({"error": "scheduled_at required"}), 400
    try:
        cms_service.schedule_publish(id, reviewer_id=get_current_actor_id(), scheduled_at=scheduled_at)
        return jsonify({"status": "scheduled"})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/content/<int:id>/withdraw", methods=["POST"])
@jwt_required
@scope_required("content.write")
def api_withdraw(id):
    item = db.session.get(ContentItem, id)
    if not item:
        return jsonify({"error": "Not found"}), 404
    actor = db.session.get(User, get_current_actor_id())
    if not actor or not check_region_access(item, actor):
        return jsonify({"error": "Access denied"}), 403
    try:
        cms_service.withdraw_content(id, user_id=get_current_actor_id())
        return jsonify({"status": "withdrawn"})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


# --- Search ---
@bp.route("/search", methods=["GET"])
@jwt_required
@scope_required("search.read")
def api_search():
    q = request.args.get("q", "")
    if not q:
        return jsonify({"error": "Query parameter 'q' required"}), 400
    results, count = search_service.search(q, record_type=request.args.get("type"))
    return jsonify({"query": q, "count": count,
                    "results": [{"id": r.id, "type": r.record_type, "title": r.title} for r in results]})


@bp.route("/search/insights", methods=["GET"])
@jwt_required
@scope_required("search.read")
def api_search_insights():
    trending = search_service.get_trending_terms()
    zero = search_service.get_zero_result_queries()
    return jsonify({"trending": [{"term": t, "count": c} for t, c in trending],
                    "zero_results": [{"term": t, "count": c} for t, c in zero]})


# --- Resources ---
@bp.route("/resources", methods=["GET"])
@jwt_required
@scope_required("dispatch.read")
def api_resources():
    items = dispatch_service.get_resources(resource_type=request.args.get("type"))
    return jsonify([{"id": r.id, "type": r.resource_type, "name": r.name, "code": r.code} for r in items])


@bp.route("/resources", methods=["POST"])
@jwt_required
@scope_required("dispatch.write")
def api_resource_create():
    data = request.get_json(silent=True) or {}
    try:
        r = dispatch_service.create_resource(
            resource_type=data["resource_type"], name=data["name"], code=data["code"],
            region_id=data.get("region_id"),
        )
        return jsonify({"id": r.id, "name": r.name}), 201
    except (ValueError, KeyError) as e:
        return jsonify({"error": str(e)}), 400


# --- Schedules ---
@bp.route("/schedules", methods=["GET"])
@jwt_required
@scope_required("dispatch.read")
def api_schedules():
    query = dispatch_service.get_schedule_items()
    actor = db.session.get(User, get_current_actor_id())
    if actor:
        query = apply_region_filter(query, ScheduleItem, actor)
    items = query.limit(50).all()
    return jsonify([_serialize_schedule(i) for i in items])


@bp.route("/schedules/auto-assign", methods=["POST"])
@jwt_required
@scope_required("dispatch.write")
def api_auto_assign():
    unscheduled = ScheduleItem.query.filter_by(status="draft").all()
    results = dispatch_service.auto_assign(unscheduled, user_id=get_current_actor_id())
    return jsonify({"results": results})


@bp.route("/schedules/suggest", methods=["GET"])
@jwt_required
@scope_required("dispatch.read")
def api_suggest():
    unscheduled = ScheduleItem.query.filter(
        ScheduleItem.status == "draft",
        ScheduleItem.classroom_id.is_(None),
    ).all()
    suggestions = dispatch_service.suggest_assignments(unscheduled)
    return jsonify({"suggestions": suggestions})


@bp.route("/schedules/<int:id>/confirm-suggestion", methods=["POST"])
@jwt_required
@scope_required("dispatch.write")
def api_confirm_suggestion(id):
    sched = db.session.get(ScheduleItem, id)
    if not sched:
        return jsonify({"error": "Not found"}), 404
    actor = db.session.get(User, get_current_actor_id())
    if not actor or not check_region_access(sched, actor):
        return jsonify({"error": "Access denied"}), 403
    data = request.get_json(silent=True) or {}
    try:
        item = dispatch_service.confirm_suggestion(
            id, data["classroom_id"], data["instructor_id"],
            user_id=get_current_actor_id(),
        )
        return jsonify(_serialize_schedule(item))
    except (ValueError, KeyError) as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/schedules/<int:id>/reschedule", methods=["POST"])
@jwt_required
@scope_required("dispatch.write")
def api_reschedule(id):
    sched = db.session.get(ScheduleItem, id)
    if not sched:
        return jsonify({"error": "Not found"}), 404
    actor = db.session.get(User, get_current_actor_id())
    if not actor or not check_region_access(sched, actor):
        return jsonify({"error": "Access denied"}), 403
    data = request.get_json(silent=True) or {}
    from app.utils.date_helpers import parse_date_us
    from datetime import datetime
    new_date = parse_date_us(data.get("new_date"))
    if not new_date:
        return jsonify({"error": "new_date required"}), 400
    try:
        item = dispatch_service.reschedule(
            id, new_date,
            datetime.strptime(data["new_start"], "%H:%M").time(),
            datetime.strptime(data["new_end"], "%H:%M").time(),
            user_id=get_current_actor_id(),
        )
        return jsonify(_serialize_schedule(item))
    except (ValueError, KeyError) as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/schedules/<int:id>/substitute", methods=["POST"])
@jwt_required
@scope_required("dispatch.write")
def api_substitute(id):
    sched = db.session.get(ScheduleItem, id)
    if not sched:
        return jsonify({"error": "Not found"}), 404
    actor = db.session.get(User, get_current_actor_id())
    if not actor or not check_region_access(sched, actor):
        return jsonify({"error": "Access denied"}), 403
    data = request.get_json(silent=True) or {}
    try:
        item = dispatch_service.substitute_resource(
            id, data["resource_type"], data["new_resource_id"], user_id=get_current_actor_id(),
        )
        return jsonify(_serialize_schedule(item))
    except (ValueError, KeyError) as e:
        return jsonify({"error": str(e)}), 400


# --- Service Items ---
@bp.route("/service-items", methods=["GET"])
@jwt_required
@scope_required("orders.read")
def api_service_items():
    items = ServiceItem.query.filter_by(active=True).all()
    return jsonify([{"id": s.id, "code": s.code, "name": s.name,
                     "pricing_model": s.pricing_model} for s in items])


# --- Orders ---
@bp.route("/orders", methods=["GET"])
@jwt_required
@scope_required("orders.read")
def api_orders():
    query = order_service.get_order_list(state=request.args.get("state"))
    actor = db.session.get(User, get_current_actor_id())
    if actor:
        query = apply_region_filter(query, Order, actor)
    items = query.limit(50).all()
    return jsonify([_serialize_order(o) for o in items])


@bp.route("/orders", methods=["POST"])
@jwt_required
@scope_required("orders.write")
def api_order_create():
    data = request.get_json(silent=True) or {}
    try:
        order = order_service.create_order(
            customer_name=data["customer_name"], region_id=data["region_id"],
            user_id=get_current_actor_id(), customer_org=data.get("customer_org"),
            service_address=data.get("service_address"),
            line_items=data.get("line_items", []),
        )
        return jsonify(_serialize_order(order)), 201
    except (ValueError, KeyError) as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/orders/<int:id>/pay", methods=["POST"])
@jwt_required
@scope_required("orders.write")
def api_order_pay(id):
    order = db.session.get(Order, id)
    if not order:
        return jsonify({"error": "Not found"}), 404
    actor = db.session.get(User, get_current_actor_id())
    if not actor or not check_region_access(order, actor):
        return jsonify({"error": "Access denied"}), 403
    data = request.get_json(silent=True) or {}
    try:
        order_service.record_payment(
            id, data["tender_type"], data["receipt_number"],
            data["amount"], user_id=get_current_actor_id(),
        )
        order_service.transition_order(id, "paid", user_id=get_current_actor_id())
        return jsonify({"status": "paid"})
    except (ValueError, KeyError) as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/orders/<int:id>/cancel", methods=["POST"])
@jwt_required
@scope_required("orders.write")
def api_order_cancel(id):
    order = db.session.get(Order, id)
    if not order:
        return jsonify({"error": "Not found"}), 404
    actor = db.session.get(User, get_current_actor_id())
    if not actor or not check_region_access(order, actor):
        return jsonify({"error": "Access denied"}), 403
    try:
        order_service.transition_order(id, "canceled", user_id=get_current_actor_id())
        return jsonify({"status": "canceled"})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/orders/<int:id>/complete", methods=["POST"])
@jwt_required
@scope_required("orders.write")
def api_order_complete(id):
    order = db.session.get(Order, id)
    if not order:
        return jsonify({"error": "Not found"}), 404
    actor = db.session.get(User, get_current_actor_id())
    if not actor or not check_region_access(order, actor):
        return jsonify({"error": "Access denied"}), 403
    try:
        order_service.transition_order(id, "completed", user_id=get_current_actor_id())
        return jsonify({"status": "completed"})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/orders/<int:id>/refund", methods=["POST"])
@jwt_required
@scope_required("orders.write")
def api_order_refund(id):
    order = db.session.get(Order, id)
    if not order:
        return jsonify({"error": "Not found"}), 404
    actor = db.session.get(User, get_current_actor_id())
    if not actor or not check_region_access(order, actor):
        return jsonify({"error": "Access denied"}), 403
    try:
        order_service.transition_order(id, "refunded", user_id=get_current_actor_id())
        return jsonify({"status": "refunded"})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


# --- Reconciliation ---
@bp.route("/reconciliation-runs", methods=["POST"])
@jwt_required
@scope_required("orders.write")
def api_reconciliation():
    data = request.get_json(silent=True) or {}
    try:
        run = order_service.create_reconciliation_run(
            data["label"], user_id=get_current_actor_id(),
            order_ids=data["order_ids"], actual_amounts=data["actual_amounts"],
        )
        return jsonify({"id": run.id}), 201
    except (ValueError, KeyError) as e:
        return jsonify({"error": str(e)}), 400


# --- KPIs ---
@bp.route("/kpis", methods=["GET"])
@jwt_required
@scope_required("analytics.read")
def api_kpis():
    scope = request.args.get("scope", "overview")
    filters = {}
    region_id = request.args.get("region_id", type=int)
    if region_id:
        filters["region_id"] = region_id
    metrics = analytics_service.get_kpis(scope, filters)
    return jsonify(metrics)


# --- Reports ---
@bp.route("/reports", methods=["POST"])
@jwt_required
@scope_required("analytics.export")
def api_report_create():
    data = request.get_json(silent=True) or {}
    job = analytics_service.create_report_job(
        data.get("report_type", "orders"), data.get("filters", {}), user_id=get_current_actor_id(),
    )
    return jsonify({"id": job.id, "status": job.status}), 201


@bp.route("/reports/<int:id>", methods=["GET"])
@jwt_required
@scope_required("analytics.read")
def api_report_detail(id):
    job = analytics_service.get_report_job(id)
    if not job:
        return jsonify({"error": "Not found"}), 404
    actor_id = get_current_actor_id()
    if job.requested_by != actor_id and "analytics.view" not in g.get("api_scopes", []):
        return jsonify({"error": "Access denied"}), 403
    return jsonify({"id": job.id, "status": job.status, "row_count": job.row_count,
                    "error": job.error_text})


# --- Files ---
@bp.route("/files/<int:id>/download-link", methods=["GET"])
@jwt_required
@scope_required("files.read")
def api_download_link(id):
    """Generate a signed, time-limited download URL for API clients."""
    from app.models.files import Attachment
    from app.services.access_policy import can_access_attachment
    att = db.session.get(Attachment, id)
    if not att or att.deleted_at:
        return jsonify({"error": "File not found"}), 404
    # Object-level access check using uploader identity from API client
    actor_id = get_current_actor_id()
    from app.models.user import User
    actor_user = db.session.get(User, actor_id)
    if not actor_user or not can_access_attachment(att, actor_user):
        return jsonify({"error": "Access denied to this attachment"}), 403
    url = file_service.generate_signed_url(id, user_id=actor_id, api=True)
    return jsonify({"download_url": url})


@bp.route("/files/<int:id>/download", methods=["GET"])
@jwt_required
@scope_required("files.read")
def api_file_download(id):
    """JWT-protected file download with signed URL TTL enforcement.

    API clients must first obtain a signed URL via GET /files/<id>/download-link,
    then use the returned URL params (sig, expires, uid) on this endpoint.
    Direct access without valid signature is denied.
    """
    sig = request.args.get("sig", "")
    expires = request.args.get("expires", "")
    uid = request.args.get("uid", "")
    if not sig or not expires or not uid:
        return jsonify({"error": "Signed URL parameters required. Use GET /files/<id>/download-link first."}), 403
    if not file_service.verify_signed_url(id, sig, expires, uid):
        return jsonify({"error": "Invalid or expired download link"}), 403
    # Bind signed URL to authenticated principal: uid must match current actor
    current_actor = str(get_current_actor_id())
    if str(uid) != current_actor:
        return jsonify({"error": "Download link was issued to a different principal"}), 403
    from app.models.files import Attachment, FileDownloadAudit
    from app.services.access_policy import can_access_attachment
    att = db.session.get(Attachment, id)
    if not att or att.deleted_at:
        return jsonify({"error": "File not found"}), 404
    # Object-level access check
    from app.models.user import User
    actor_user = db.session.get(User, get_current_actor_id())
    if not actor_user or not can_access_attachment(att, actor_user):
        return jsonify({"error": "Access denied to this attachment"}), 403
    path = Path(att.storage_path)
    if not path.exists():
        return jsonify({"error": "File not available"}), 404
    audit = FileDownloadAudit(
        attachment_id=att.id,
        user_id=get_current_actor_id(),
        watermark_applied=False,
    )
    db.session.add(audit)
    db.session.commit()
    from flask import send_file
    return send_file(str(path), as_attachment=True, download_name=att.original_filename)


# --- Outbox ---
@bp.route("/outbox-events/pull", methods=["GET"])
@jwt_required
@scope_required("outbox.read")
def api_outbox_pull():
    consumer = request.args.get("consumer")
    if not consumer:
        return jsonify({"error": "Query parameter 'consumer' is required"}), 400
    events = outbox_service.pull_events(consumer_name=consumer)
    return jsonify([{
        "id": e.id, "topic": e.topic, "aggregate_type": e.aggregate_type,
        "aggregate_id": e.aggregate_id, "payload": json.loads(e.payload_json),
        "available_at": e.available_at.isoformat(),
    } for e in events])


@bp.route("/outbox-events/<int:id>/ack", methods=["POST"])
@jwt_required
@scope_required("outbox.write")
def api_outbox_ack(id):
    data = request.get_json(silent=True) or {}
    consumer = data.get("consumer") or request.args.get("consumer")
    if not consumer:
        return jsonify({"error": "Consumer name is required for acknowledgment"}), 400
    try:
        outbox_service.acknowledge_event(id, consumer_name=consumer)
        return jsonify({"status": "acknowledged"})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


# --- GraphQL ---
@bp.route("/graphql", methods=["POST"])
@jwt_required
def api_graphql():
    from app.graphql.schema import execute_query
    from app.utils.auth_context import get_current_actor_id
    data = request.get_json(silent=True) or {}
    query = data.get("query", "")
    variables = data.get("variables")
    context = {
        "actor_id": get_current_actor_id(),
        "scopes": set(g.get("api_scopes", [])),
    }
    result = execute_query(query, variables, context=context)
    return jsonify(result)


# --- Serializers ---
def _serialize_content(item):
    v = item.current_version
    return {
        "id": item.id, "slug": item.slug, "state": item.workflow_state,
        "title": v.title if v else "", "summary": v.summary if v else "",
        "media_type": item.media_type, "region_id": item.region_id,
        "is_pinned": item.is_pinned, "is_recommended": item.is_recommended,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "published_at": item.published_at.isoformat() if item.published_at else None,
    }


def _serialize_order(order):
    return {
        "id": order.id, "order_number": order.order_number,
        "customer_name": order.customer_name, "state": order.state,
        "subtotal": str(order.subtotal_amount), "tax": str(order.tax_amount),
        "total": str(order.total_amount), "paid": str(order.paid_amount),
        "region_id": order.region_id,
        "has_device_identifier": order.encrypted_device_identifier is not None,
        "has_credit_history": order.encrypted_credit_history is not None,
        "created_at": order.created_at.isoformat() if order.created_at else None,
    }


def _serialize_schedule(item):
    return {
        "id": item.id, "title": item.title, "status": item.status,
        "date": str(item.scheduled_date), "start": str(item.start_time),
        "end": str(item.end_time), "classroom_id": item.classroom_id,
        "instructor_id": item.instructor_id, "region_id": item.region_id,
    }
