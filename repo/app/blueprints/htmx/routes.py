"""HTMX partial API endpoints.

Session-authenticated (Flask-Login), CSRF-protected by Flask-WTF.
These serve HTML partials for HTMX interactions, consuming the service layer.
"""

from flask import request, render_template
from flask_login import current_user
from app.blueprints.htmx import bp
from app.services import cms_service, order_service, dispatch_service, search_service, analytics_service
from app.services.access_policy import apply_region_filter
from app.utils.pagination import paginate_query
from app.utils.date_helpers import parse_date_us


@bp.route("/search", methods=["GET"])
def htmx_search():
    if not current_user.is_authenticated:
        return "", 401
    query_text = request.args.get("q", "").strip()
    record_type = request.args.get("type")
    region_id = request.args.get("region_id", type=int)
    media_type = request.args.get("media_type")
    category_id = request.args.get("category_id", type=int)
    date_from = parse_date_us(request.args.get("date_from"))
    date_to = parse_date_us(request.args.get("date_to"))
    page = request.args.get("page", 1, type=int)
    results = []
    result_count = 0
    if query_text:
        results, result_count = search_service.search(
            query_text, user_id=current_user.id, record_type=record_type,
            region_id=region_id, media_type=media_type,
            date_from=date_from, date_to=date_to, category_id=category_id,
            page=page,
        )
    return render_template("search/results_partial.html", query=query_text,
                          results=results, result_count=result_count)


@bp.route("/content", methods=["GET"])
def htmx_content_list():
    if not current_user.is_authenticated:
        return "", 401
    if not current_user.has_any_permission("content.create", "content.edit", "content.review", "content.publish"):
        return "", 403
    from app.models.cms import ContentItem
    state = request.args.get("state")
    region_id = request.args.get("region_id", type=int)
    query = cms_service.get_content_list(state=state, region_id=region_id)
    query = apply_region_filter(query, ContentItem, current_user)
    pagination = paginate_query(query)
    return render_template("cms/content_list_partial.html", pagination=pagination)


@bp.route("/orders", methods=["GET"])
def htmx_order_list():
    if not current_user.is_authenticated:
        return "", 401
    if not current_user.has_any_permission("orders.manage"):
        return "", 403
    from app.models.catalog import Order
    state = request.args.get("state")
    region_id = request.args.get("region_id", type=int)
    query = order_service.get_order_list(state=state, region_id=region_id)
    query = apply_region_filter(query, Order, current_user)
    pagination = paginate_query(query)
    return render_template("orders/order_list_partial.html", pagination=pagination,
                          current_state=state, current_region_id=region_id)


@bp.route("/schedules", methods=["GET"])
def htmx_schedule_list():
    if not current_user.is_authenticated:
        return "", 401
    if not current_user.has_any_permission("dispatch.manage_schedule"):
        return "", 403
    from app.models.dispatch import ScheduleItem
    date_str = request.args.get("date")
    sched_date = parse_date_us(date_str) if date_str else None
    status = request.args.get("status")
    region_id = request.args.get("region_id", type=int)
    query = dispatch_service.get_schedule_items(scheduled_date=sched_date, status=status, region_id=region_id)
    query = apply_region_filter(query, ScheduleItem, current_user)
    pagination = paginate_query(query)
    return render_template("dispatch/schedule_partial.html", pagination=pagination,
                          current_date=date_str, current_status=status, current_region_id=region_id)


@bp.route("/kpis", methods=["GET"])
def htmx_kpis():
    if not current_user.is_authenticated:
        return "", 401
    if not current_user.has_any_permission("analytics.view"):
        return "", 403
    scope = request.args.get("scope", "overview")
    region_id = request.args.get("region_id", type=int)
    filters = {}
    if region_id:
        filters["region_id"] = region_id
    date_from_raw = request.args.get("date_from")
    date_to_raw = request.args.get("date_to")
    if date_from_raw:
        parsed = parse_date_us(date_from_raw)
        if parsed:
            filters["date_from"] = parsed.isoformat()
    if date_to_raw:
        parsed = parse_date_us(date_to_raw)
        if parsed:
            filters["date_to"] = parsed.isoformat()
    metrics = analytics_service.get_kpis(scope, filters, current_user.get_permissions())
    return render_template("analytics/kpis_partial.html", metrics=metrics)
