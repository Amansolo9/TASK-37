"""Analytics and reporting routes."""

from flask import render_template, redirect, url_for, flash, request, send_file, jsonify
from flask_login import login_required, current_user
from functools import wraps
from app.blueprints.analytics import bp
from app.services import analytics_service
from app.models.analytics import ReportJob
from app.models.region import Region
from app.utils.date_helpers import parse_date_us
from pathlib import Path


def permission_required(*perms):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not current_user.has_any_permission(*perms):
                flash("Permission denied.", "danger")
                return redirect(url_for("dashboard"))
            return f(*args, **kwargs)
        return decorated
    return decorator


@bp.route("/kpis")
@login_required
@permission_required("analytics.view")
def kpis():
    scope = request.args.get("scope", "overview")
    region_id = request.args.get("region_id", type=int)
    date_from_raw = request.args.get("date_from")
    date_to_raw = request.args.get("date_to")
    filters = {}
    # Enforce actor-region scope
    from app.services.access_policy import validate_region_for_create, get_actor_region_ids
    if region_id:
        if not validate_region_for_create(current_user, region_id):
            flash("Region is outside your authorized scope.", "danger")
            region_id = None  # fall back to scoped default
    if region_id:
        filters["region_id"] = region_id
    if date_from_raw:
        parsed = parse_date_us(date_from_raw)
        if parsed:
            filters["date_from"] = parsed.isoformat()
        else:
            flash("Invalid 'from' date format. Use MM/DD/YYYY.", "warning")
    if date_to_raw:
        parsed = parse_date_us(date_to_raw)
        if parsed:
            filters["date_to"] = parsed.isoformat()
        else:
            flash("Invalid 'to' date format. Use MM/DD/YYYY.", "warning")

    metrics = analytics_service.get_kpis(scope, filters, current_user.get_permissions())
    regions = Region.query.filter_by(active=True).all()
    is_htmx = request.headers.get("HX-Request")
    template = "analytics/kpis_partial.html" if is_htmx else "analytics/kpis.html"
    return render_template(template, metrics=metrics, regions=regions,
                          current_scope=scope, current_region_id=region_id)


@bp.route("/reports")
@login_required
@permission_required("analytics.view")
def reports():
    from app.utils.pagination import paginate_query
    query = ReportJob.query.filter_by(requested_by=current_user.id).order_by(
        ReportJob.created_at.desc()
    )
    pagination = paginate_query(query)
    return render_template("analytics/reports.html", pagination=pagination)


@bp.route("/reports/new", methods=["POST"])
@login_required
@permission_required("analytics.export")
def report_new():
    report_type = request.form.get("report_type", "orders")
    filters = {}
    region_id = request.form.get("region_id", type=int)
    from app.services.access_policy import validate_region_for_create
    if region_id and not validate_region_for_create(current_user, region_id):
        flash("Region is outside your authorized scope.", "danger")
        region_id = None
    if region_id:
        filters["region_id"] = region_id
    state = request.form.get("state")
    if state:
        filters["state"] = state
    date_from_raw = request.form.get("date_from")
    if date_from_raw:
        parsed = parse_date_us(date_from_raw)
        if parsed:
            filters["date_from"] = parsed.isoformat()
        else:
            flash("Invalid 'from' date. Use MM/DD/YYYY.", "warning")
    date_to_raw = request.form.get("date_to")
    if date_to_raw:
        parsed = parse_date_us(date_to_raw)
        if parsed:
            filters["date_to"] = parsed.isoformat()
        else:
            flash("Invalid 'to' date. Use MM/DD/YYYY.", "warning")

    job = analytics_service.create_report_job(report_type, filters, current_user.id)
    if job.status == "completed":
        flash("Report generated.", "success")
    else:
        flash("Report queued for generation.", "info")
    return redirect(url_for("analytics.report_detail", job_id=job.id))


@bp.route("/reports/<int:job_id>")
@login_required
@permission_required("analytics.view")
def report_detail(job_id):
    job = analytics_service.get_report_job(job_id)
    if not job:
        flash("Report not found.", "danger")
        return redirect(url_for("analytics.reports"))
    if job.requested_by != current_user.id and not current_user.has_permission("admin.view_audit_logs"):
        flash("Access denied.", "danger")
        return redirect(url_for("analytics.reports"))
    is_htmx = request.headers.get("HX-Request")
    if is_htmx:
        return render_template("analytics/report_status_partial.html", job=job)
    return render_template("analytics/report_detail.html", job=job)


@bp.route("/reports/<int:job_id>/download")
@login_required
@permission_required("analytics.export")
def report_download(job_id):
    job = analytics_service.get_report_job(job_id)
    if not job or job.status != "completed" or not job.result_file_path:
        flash("Report not available.", "danger")
        return redirect(url_for("analytics.reports"))
    if job.requested_by != current_user.id and not current_user.has_permission("admin.view_audit_logs"):
        flash("Access denied.", "danger")
        return redirect(url_for("analytics.reports"))
    path = Path(job.result_file_path)
    if not path.exists():
        flash("Report file missing.", "danger")
        return redirect(url_for("analytics.reports"))
    return send_file(str(path), as_attachment=True,
                    download_name=f"report_{job.report_type}_{job.id}.csv")
