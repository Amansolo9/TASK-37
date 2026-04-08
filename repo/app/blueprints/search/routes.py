"""Search routes."""

from flask import render_template, request
from flask_login import login_required, current_user
from app.blueprints.search import bp
from app.services import search_service
from app.models.region import Region
from app.utils.date_helpers import parse_date_us


@bp.route("")
@login_required
def search_page():
    query = request.args.get("q", "").strip()
    record_type = request.args.get("type")
    region_id = request.args.get("region_id", type=int)
    media_type = request.args.get("media_type")
    category_id = request.args.get("category_id", type=int)
    date_from = parse_date_us(request.args.get("date_from"))
    date_to = parse_date_us(request.args.get("date_to"))
    page = request.args.get("page", 1, type=int)

    results = []
    result_count = 0
    trending = search_service.get_trending_terms(days=7)

    # Validate submitted region filter against actor scope
    from app.services.access_policy import validate_region_for_create
    if region_id and not validate_region_for_create(current_user, region_id):
        region_id = None  # clamp to unfiltered (results still scoped below)

    if query:
        results, result_count = search_service.search(
            query, user_id=current_user.id, record_type=record_type,
            region_id=region_id, media_type=media_type,
            date_from=date_from, date_to=date_to, category_id=category_id,
            page=page,
        )
        # Apply actor-region isolation to search results
        from app.services.access_policy import get_actor_region_ids
        region_ids = get_actor_region_ids(current_user)
        if region_ids is not None:
            results = [r for r in results if r.region_id is None or r.region_id in region_ids]
            result_count = len(results)

    regions = Region.query.filter_by(active=True).all()
    from app.models.region import Category
    categories = Category.query.filter_by(active=True).all()
    is_htmx = request.headers.get("HX-Request")
    template = "search/results_partial.html" if is_htmx else "search/search.html"
    return render_template(template, query=query, results=results,
                          result_count=result_count, trending=trending,
                          regions=regions, categories=categories,
                          current_type=record_type,
                          current_region_id=region_id, current_media_type=media_type,
                          current_category_id=category_id)


@bp.route("/insights")
@login_required
def insights():
    if not current_user.has_any_permission("content.review", "admin.manage_settings", "analytics.view"):
        from flask import flash, redirect, url_for
        flash("Permission denied.", "danger")
        return redirect(url_for("dashboard"))
    trending_7d = search_service.get_trending_terms(days=7)
    trending_30d = search_service.get_trending_terms(days=30, limit=20)
    zero_results = search_service.get_zero_result_queries(days=30)
    return render_template("search/insights.html", trending_7d=trending_7d,
                          trending_30d=trending_30d, zero_results=zero_results)
