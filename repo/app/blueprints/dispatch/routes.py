"""Dispatch routes for resource and schedule management."""

from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from functools import wraps
from app.blueprints.dispatch import bp
from app.services import dispatch_service
from app.models.dispatch import Resource, TimeSlotTemplate, ScheduleItem, ScheduleConflict, ScheduleChange
from app.models.region import Region
from app.forms.dispatch_forms import ResourceForm, TimeSlotForm, ScheduleItemForm
from app.utils.pagination import paginate_query
from app.utils.date_helpers import parse_date_us
from app.services.access_policy import apply_region_filter, check_region_access
from app.extensions import db
from datetime import datetime


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


@bp.route("/resources")
@login_required
@permission_required("dispatch.manage_resources")
def resources():
    rtype = request.args.get("type")
    items = dispatch_service.get_resources(resource_type=rtype)
    return render_template("dispatch/resources.html", resources=items, current_type=rtype)


@bp.route("/resources/new", methods=["GET", "POST"])
@login_required
@permission_required("dispatch.manage_resources")
def resource_new():
    form = ResourceForm()
    form.region_id.choices = [(0, "-- None --")] + [(r.id, r.name) for r in Region.query.filter_by(active=True).all()]
    if form.validate_on_submit():
        dispatch_service.create_resource(
            resource_type=form.resource_type.data,
            name=form.name.data, code=form.code.data,
            region_id=form.region_id.data or None,
        )
        flash("Resource created.", "success")
        return redirect(url_for("dispatch.resources"))
    return render_template("dispatch/resource_form.html", form=form)


@bp.route("/time-slots")
@login_required
@permission_required("dispatch.manage_resources")
def time_slots():
    slots = TimeSlotTemplate.query.filter_by(active=True).order_by(TimeSlotTemplate.start_time).all()
    return render_template("dispatch/time_slots.html", slots=slots)


@bp.route("/schedule")
@login_required
@permission_required("dispatch.manage_schedule")
def schedule():
    date_str = request.args.get("date")
    sched_date = parse_date_us(date_str) if date_str else None
    status = request.args.get("status")
    region_id = request.args.get("region_id", type=int)
    query = dispatch_service.get_schedule_items(scheduled_date=sched_date, status=status, region_id=region_id)
    query = apply_region_filter(query, ScheduleItem, current_user)
    pagination = paginate_query(query)
    regions = Region.query.filter_by(active=True).all()
    is_htmx = request.headers.get("HX-Request")
    template = "dispatch/schedule_partial.html" if is_htmx else "dispatch/schedule.html"
    return render_template(template, pagination=pagination, regions=regions,
                          current_date=date_str, current_status=status, current_region_id=region_id)


@bp.route("/schedule/new", methods=["GET", "POST"])
@login_required
@permission_required("dispatch.manage_schedule")
def schedule_new():
    form = ScheduleItemForm()
    _populate_schedule_choices(form)
    if form.validate_on_submit():
        sched_date = parse_date_us(form.scheduled_date.data)
        if not sched_date:
            flash("Invalid date format. Use MM/DD/YYYY.", "danger")
            return render_template("dispatch/schedule_form.html", form=form)
        item = dispatch_service.create_schedule_item(
            title=form.title.data, region_id=form.region_id.data,
            scheduled_date=sched_date,
            start_time=datetime.strptime(form.start_time.data, "%H:%M").time(),
            end_time=datetime.strptime(form.end_time.data, "%H:%M").time(),
            classroom_id=form.classroom_id.data or None,
            instructor_id=form.instructor_id.data or None,
            time_slot_template_id=form.time_slot_template_id.data or None,
            user_id=current_user.id, notes=form.notes.data,
        )
        if item.status == "conflict":
            flash("Scheduled with conflicts detected. Please review.", "warning")
        else:
            flash("Schedule item created.", "success")
        return redirect(url_for("dispatch.schedule"))
    return render_template("dispatch/schedule_form.html", form=form)


@bp.route("/schedule/<int:id>/reschedule", methods=["POST"])
@login_required
@permission_required("dispatch.manage_schedule")
def reschedule_item(id):
    sched = db.session.get(ScheduleItem, id)
    if not sched or not check_region_access(sched, current_user):
        flash("Access denied.", "danger")
        return redirect(url_for("dispatch.schedule"))
    new_date = parse_date_us(request.form.get("new_date"))
    new_start = request.form.get("new_start")
    new_end = request.form.get("new_end")
    if not new_date or not new_start or not new_end:
        flash("Date, start time, and end time required.", "danger")
        return redirect(url_for("dispatch.schedule"))
    try:
        dispatch_service.reschedule(
            id, new_date,
            datetime.strptime(new_start, "%H:%M").time(),
            datetime.strptime(new_end, "%H:%M").time(),
            current_user.id,
            new_classroom_id=request.form.get("classroom_id", type=int),
            new_instructor_id=request.form.get("instructor_id", type=int),
        )
        flash("Item rescheduled.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("dispatch.schedule"))


@bp.route("/schedule/<int:id>/substitute", methods=["POST"])
@login_required
@permission_required("dispatch.manage_schedule")
def substitute(id):
    sched = db.session.get(ScheduleItem, id)
    if not sched or not check_region_access(sched, current_user):
        flash("Access denied.", "danger")
        return redirect(url_for("dispatch.schedule"))
    resource_type = request.form.get("resource_type")
    new_resource_id = request.form.get("new_resource_id", type=int)
    if not resource_type or not new_resource_id:
        flash("Resource type and new resource required.", "danger")
        return redirect(url_for("dispatch.schedule"))
    try:
        dispatch_service.substitute_resource(id, resource_type, new_resource_id, current_user.id)
        flash("Substitution applied.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("dispatch.schedule"))


@bp.route("/schedule/auto-assign", methods=["POST"])
@login_required
@permission_required("dispatch.manage_schedule")
def auto_assign():
    unscheduled = ScheduleItem.query.filter(
        ScheduleItem.status == "draft",
        ScheduleItem.classroom_id.is_(None),
    ).all()
    if not unscheduled:
        flash("No unscheduled items to assign.", "info")
        return redirect(url_for("dispatch.schedule"))
    results = dispatch_service.auto_assign(unscheduled, current_user.id)
    assigned = sum(1 for r in results if r["status"] == "assigned")
    conflicts = sum(1 for r in results if r["status"] == "conflict")
    flash(f"Auto-assigned {assigned} items. {conflicts} with conflicts.", "info")
    return redirect(url_for("dispatch.schedule"))


@bp.route("/schedule/suggest", methods=["GET", "POST"])
@login_required
@permission_required("dispatch.manage_schedule")
def suggest():
    """Semi-automatic scheduling: generate suggestions for unscheduled items."""
    unscheduled = ScheduleItem.query.filter(
        ScheduleItem.status == "draft",
        ScheduleItem.classroom_id.is_(None),
    ).all()
    if not unscheduled:
        flash("No unscheduled items to suggest for.", "info")
        return redirect(url_for("dispatch.schedule"))
    suggestions = dispatch_service.suggest_assignments(unscheduled)
    return render_template("dispatch/suggestions.html", suggestions=suggestions)


@bp.route("/schedule/<int:id>/confirm-suggestion", methods=["POST"])
@login_required
@permission_required("dispatch.manage_schedule")
def confirm_suggestion(id):
    """Confirm a semi-auto scheduling suggestion."""
    sched = db.session.get(ScheduleItem, id)
    if not sched or not check_region_access(sched, current_user):
        flash("Access denied.", "danger")
        return redirect(url_for("dispatch.schedule"))
    classroom_id = request.form.get("classroom_id", type=int)
    instructor_id = request.form.get("instructor_id", type=int)
    if not classroom_id or not instructor_id:
        flash("Classroom and instructor are required.", "danger")
        return redirect(url_for("dispatch.suggest"))
    try:
        dispatch_service.confirm_suggestion(id, classroom_id, instructor_id, current_user.id)
        flash("Assignment confirmed.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("dispatch.schedule"))


@bp.route("/conflicts")
@login_required
@permission_required("dispatch.resolve_conflicts")
def conflicts():
    items = dispatch_service.get_unresolved_conflicts()
    return render_template("dispatch/conflicts.html", conflicts=items)


@bp.route("/conflicts/<int:id>/resolve", methods=["POST"])
@login_required
@permission_required("dispatch.resolve_conflicts")
def resolve_conflict(id):
    try:
        dispatch_service.resolve_conflict(id, current_user.id)
        flash("Conflict resolved.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("dispatch.conflicts"))


@bp.route("/changes")
@login_required
@permission_required("dispatch.view_change_notices")
def changes():
    items = dispatch_service.get_recent_changes()
    return render_template("dispatch/changes.html", changes=items)


def _populate_schedule_choices(form):
    form.region_id.choices = [(r.id, r.name) for r in Region.query.filter_by(active=True).all()]
    form.classroom_id.choices = [(0, "-- None --")] + [
        (r.id, r.name) for r in Resource.query.filter_by(resource_type="classroom", active=True).all()
    ]
    form.instructor_id.choices = [(0, "-- None --")] + [
        (r.id, r.name) for r in Resource.query.filter_by(resource_type="instructor", active=True).all()
    ]
    form.time_slot_template_id.choices = [(0, "-- None --")] + [
        (t.id, t.name) for t in TimeSlotTemplate.query.filter_by(active=True).all()
    ]
