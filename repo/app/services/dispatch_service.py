"""Dispatch/scheduling service with conflict detection and auto-assignment."""

import json
from datetime import datetime, date, time
from app.extensions import db
from app.models.dispatch import (
    Resource, ResourceAvailability, TimeSlotTemplate,
    ScheduleItem, ScheduleConflict, ScheduleChange,
)
from app.services.audit_service import log_action

SCHEDULE_STATES = {"draft", "scheduled", "conflict", "completed", "canceled"}
SCHEDULE_TRANSITIONS = {
    "draft": ["scheduled"],
    "scheduled": ["conflict", "completed", "canceled"],
    "conflict": ["scheduled", "canceled"],
}


def get_resources(resource_type=None, region_id=None):
    q = Resource.query.filter_by(active=True)
    if resource_type:
        q = q.filter_by(resource_type=resource_type)
    if region_id:
        q = q.filter_by(region_id=region_id)
    return q.order_by(Resource.name).all()


def create_resource(resource_type, name, code, region_id=None, metadata_json=None):
    r = Resource(resource_type=resource_type, name=name, code=code,
                 region_id=region_id, metadata_json=metadata_json)
    db.session.add(r)
    db.session.commit()
    return r


def get_schedule_items(scheduled_date=None, status=None, region_id=None):
    q = ScheduleItem.query
    if scheduled_date:
        q = q.filter(ScheduleItem.scheduled_date == scheduled_date)
    if status:
        q = q.filter(ScheduleItem.status == status)
    if region_id:
        q = q.filter(ScheduleItem.region_id == region_id)
    return q.order_by(ScheduleItem.scheduled_date, ScheduleItem.start_time)


def create_schedule_item(title, region_id, scheduled_date, start_time, end_time,
                         classroom_id=None, instructor_id=None,
                         time_slot_template_id=None, user_id=None, notes=None):
    item = ScheduleItem(
        title=title, region_id=region_id, scheduled_date=scheduled_date,
        start_time=start_time, end_time=end_time,
        classroom_id=classroom_id, instructor_id=instructor_id,
        time_slot_template_id=time_slot_template_id,
        status="draft", notes=notes,
        created_by=user_id, updated_by=user_id,
    )
    db.session.add(item)
    db.session.flush()

    conflicts = detect_conflicts(item)
    if conflicts:
        item.status = "conflict"
        for c in conflicts:
            db.session.add(c)
    else:
        item.status = "scheduled"

    db.session.commit()
    try:
        from app.services.search_service import index_schedule_item
        index_schedule_item(item)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Integration operation failed for schedule_item %s: %s", item.id, e)
    if user_id:
        log_action(user_id, "schedule_created", "schedule_item", item.id)
    return item


def detect_conflicts(item):
    """Check for instructor/classroom overlaps and availability violations."""
    conflicts = []

    if item.instructor_id:
        overlapping = ScheduleItem.query.filter(
            ScheduleItem.id != item.id,
            ScheduleItem.instructor_id == item.instructor_id,
            ScheduleItem.scheduled_date == item.scheduled_date,
            ScheduleItem.status.in_(["scheduled", "conflict"]),
            ScheduleItem.start_time < item.end_time,
            ScheduleItem.end_time > item.start_time,
        ).all()
        for ov in overlapping:
            conflicts.append(ScheduleConflict(
                schedule_item_id=item.id,
                conflict_type="instructor_overlap",
                related_schedule_item_id=ov.id,
                related_resource_id=item.instructor_id,
                severity="error",
                message=f"Instructor double-booked with '{ov.title}' at {ov.start_time}-{ov.end_time}",
            ))

    if item.classroom_id:
        overlapping = ScheduleItem.query.filter(
            ScheduleItem.id != item.id,
            ScheduleItem.classroom_id == item.classroom_id,
            ScheduleItem.scheduled_date == item.scheduled_date,
            ScheduleItem.status.in_(["scheduled", "conflict"]),
            ScheduleItem.start_time < item.end_time,
            ScheduleItem.end_time > item.start_time,
        ).all()
        for ov in overlapping:
            conflicts.append(ScheduleConflict(
                schedule_item_id=item.id,
                conflict_type="classroom_overlap",
                related_schedule_item_id=ov.id,
                related_resource_id=item.classroom_id,
                severity="error",
                message=f"Classroom double-booked with '{ov.title}' at {ov.start_time}-{ov.end_time}",
            ))

    if item.time_slot_template_id:
        tpl = db.session.get(TimeSlotTemplate, item.time_slot_template_id)
        if tpl and (item.start_time < tpl.start_time or item.end_time > tpl.end_time):
            conflicts.append(ScheduleConflict(
                schedule_item_id=item.id,
                conflict_type="time_slot_violation",
                severity="warning",
                message=f"Item time {item.start_time}-{item.end_time} outside slot {tpl.start_time}-{tpl.end_time}",
            ))

    return conflicts


def resolve_conflict(conflict_id, user_id):
    conflict = db.session.get(ScheduleConflict, conflict_id)
    if not conflict:
        raise ValueError("Conflict not found.")
    conflict.resolved_at = datetime.utcnow()
    conflict.resolved_by = user_id

    item = conflict.schedule_item
    unresolved = [c for c in item.conflicts if c.id != conflict_id and c.resolved_at is None]
    if not unresolved:
        item.status = "scheduled"

    db.session.commit()
    log_action(user_id, "conflict_resolved", "schedule_conflict", conflict_id)
    return conflict


def reschedule(item_id, new_date, new_start, new_end, user_id,
               new_classroom_id=None, new_instructor_id=None):
    item = db.session.get(ScheduleItem, item_id)
    if not item:
        raise ValueError("Schedule item not found.")

    old_vals = {
        "date": str(item.scheduled_date), "start": str(item.start_time),
        "end": str(item.end_time), "classroom_id": item.classroom_id,
        "instructor_id": item.instructor_id,
    }

    item.scheduled_date = new_date
    item.start_time = new_start
    item.end_time = new_end
    if new_classroom_id is not None:
        item.classroom_id = new_classroom_id
    if new_instructor_id is not None:
        item.instructor_id = new_instructor_id
    item.updated_by = user_id

    # Clear old unresolved conflicts
    ScheduleConflict.query.filter_by(schedule_item_id=item.id).filter(
        ScheduleConflict.resolved_at.is_(None)
    ).delete()

    new_conflicts = detect_conflicts(item)
    if new_conflicts:
        item.status = "conflict"
        for c in new_conflicts:
            db.session.add(c)
    else:
        item.status = "scheduled"

    new_vals = {
        "date": str(item.scheduled_date), "start": str(item.start_time),
        "end": str(item.end_time), "classroom_id": item.classroom_id,
        "instructor_id": item.instructor_id,
    }

    change = ScheduleChange(
        schedule_item_id=item.id, change_type="reschedule",
        old_values_json=json.dumps(old_vals), new_values_json=json.dumps(new_vals),
        notice_text=f"Rescheduled from {old_vals['date']} to {new_vals['date']}",
        changed_by=user_id,
    )
    db.session.add(change)
    db.session.commit()
    try:
        from app.services.search_service import index_schedule_item
        index_schedule_item(item)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Integration operation failed for schedule_item %s: %s", item.id, e)
    log_action(user_id, "schedule_rescheduled", "schedule_item", item.id)
    from app.services.outbox_service import create_event
    try:
        create_event("schedule.changed", "schedule_item", item.id, new_vals)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Integration operation failed for schedule_item %s: %s", item.id, e)
    return item


def substitute_resource(item_id, resource_type, new_resource_id, user_id):
    item = db.session.get(ScheduleItem, item_id)
    if not item:
        raise ValueError("Schedule item not found.")

    old_vals = {}
    if resource_type == "instructor":
        old_vals["instructor_id"] = item.instructor_id
        item.instructor_id = new_resource_id
    elif resource_type == "classroom":
        old_vals["classroom_id"] = item.classroom_id
        item.classroom_id = new_resource_id

    ScheduleConflict.query.filter_by(schedule_item_id=item.id).filter(
        ScheduleConflict.resolved_at.is_(None)
    ).delete()

    new_conflicts = detect_conflicts(item)
    if new_conflicts:
        item.status = "conflict"
        for c in new_conflicts:
            db.session.add(c)
    else:
        item.status = "scheduled"

    new_vals = {"instructor_id": item.instructor_id, "classroom_id": item.classroom_id}
    change = ScheduleChange(
        schedule_item_id=item.id, change_type="substitute",
        old_values_json=json.dumps(old_vals), new_values_json=json.dumps(new_vals),
        notice_text=f"Substituted {resource_type}",
        changed_by=user_id,
    )
    db.session.add(change)
    db.session.commit()
    log_action(user_id, "schedule_substitution", "schedule_item", item.id)
    return item


def suggest_assignments(unscheduled_items):
    """Generate ranked assignment suggestions without committing.

    Returns a list of suggestions per item, each with ranked candidates.
    No database changes are made - dispatcher must confirm.
    """
    classrooms = Resource.query.filter_by(resource_type="classroom", active=True).all()
    instructors = Resource.query.filter_by(resource_type="instructor", active=True).all()
    sorted_items = sorted(unscheduled_items, key=lambda x: (x.scheduled_date, x.start_time))

    suggestions = []
    for item in sorted_items:
        candidates = []
        for cr in classrooms:
            for ins in instructors:
                item.classroom_id = cr.id
                item.instructor_id = ins.id
                conflicts = detect_conflicts(item)
                score = len(conflicts)
                # Bonus for region match
                if cr.region_id == item.region_id:
                    score -= 0.1
                if ins.region_id == item.region_id:
                    score -= 0.1
                candidates.append({
                    "classroom_id": cr.id,
                    "classroom_name": cr.name,
                    "instructor_id": ins.id,
                    "instructor_name": ins.name,
                    "conflict_count": len(conflicts),
                    "score": score,
                    "conflicts": [c.message for c in conflicts],
                })
        # Reset item to unassigned state
        item.classroom_id = None
        item.instructor_id = None

        # Sort by score ascending (fewer conflicts = better)
        candidates.sort(key=lambda c: c["score"])
        suggestions.append({
            "item_id": item.id,
            "item_title": item.title,
            "candidates": candidates[:5],  # top 5
        })

    # Expunge changes without committing
    db.session.rollback()
    return suggestions


def confirm_suggestion(item_id, classroom_id, instructor_id, user_id):
    """Confirm a semi-auto scheduling suggestion, committing the assignment."""
    item = db.session.get(ScheduleItem, item_id)
    if not item:
        raise ValueError("Schedule item not found.")

    old_vals = {
        "classroom_id": item.classroom_id,
        "instructor_id": item.instructor_id,
    }

    item.classroom_id = classroom_id
    item.instructor_id = instructor_id
    item.updated_by = user_id

    # Clear old unresolved conflicts
    ScheduleConflict.query.filter_by(schedule_item_id=item.id).filter(
        ScheduleConflict.resolved_at.is_(None)
    ).delete()

    new_conflicts = detect_conflicts(item)
    if new_conflicts:
        item.status = "conflict"
        for c in new_conflicts:
            db.session.add(c)
    else:
        item.status = "scheduled"

    change = ScheduleChange(
        schedule_item_id=item.id, change_type="semi_auto_assign",
        old_values_json=json.dumps(old_vals),
        new_values_json=json.dumps({
            "classroom_id": classroom_id,
            "instructor_id": instructor_id,
        }),
        notice_text="Semi-auto assigned (dispatcher confirmed)",
        changed_by=user_id,
    )
    db.session.add(change)
    db.session.commit()

    try:
        from app.services.search_service import index_schedule_item
        index_schedule_item(item)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Integration operation failed for schedule_item %s: %s", item.id, e)
    log_action(user_id, "schedule_semi_auto_confirmed", "schedule_item", item.id)
    return item


def auto_assign(unscheduled_items, user_id):
    """Greedy auto-assignment: sort by date, try best fit of classroom+instructor."""
    results = []
    classrooms = Resource.query.filter_by(resource_type="classroom", active=True).all()
    instructors = Resource.query.filter_by(resource_type="instructor", active=True).all()

    sorted_items = sorted(unscheduled_items, key=lambda x: (x.scheduled_date, x.start_time))

    for item in sorted_items:
        best_classroom = None
        best_instructor = None
        min_conflicts = float("inf")

        for cr in classrooms:
            for ins in instructors:
                item.classroom_id = cr.id
                item.instructor_id = ins.id
                conflicts = detect_conflicts(item)
                if len(conflicts) < min_conflicts:
                    min_conflicts = len(conflicts)
                    best_classroom = cr.id
                    best_instructor = ins.id
                if min_conflicts == 0:
                    break
            if min_conflicts == 0:
                break

        if min_conflicts == 0:
            item.classroom_id = best_classroom
            item.instructor_id = best_instructor
            item.status = "scheduled"
            results.append({"item_id": item.id, "status": "assigned",
                            "classroom_id": best_classroom, "instructor_id": best_instructor})
        else:
            item.classroom_id = best_classroom
            item.instructor_id = best_instructor
            item.status = "conflict"
            # Re-create conflicts for chosen assignment
            for c in detect_conflicts(item):
                db.session.add(c)
            results.append({"item_id": item.id, "status": "conflict",
                            "message": f"{min_conflicts} conflict(s) - needs manual resolution"})

        change = ScheduleChange(
            schedule_item_id=item.id, change_type="auto_assign",
            new_values_json=json.dumps({"classroom_id": item.classroom_id,
                                         "instructor_id": item.instructor_id}),
            notice_text="Auto-assigned by system",
            changed_by=user_id,
        )
        db.session.add(change)

    db.session.commit()
    return results


def get_unresolved_conflicts():
    return ScheduleConflict.query.filter(ScheduleConflict.resolved_at.is_(None)).all()


def get_recent_changes(limit=50):
    return ScheduleChange.query.order_by(ScheduleChange.changed_at.desc()).limit(limit).all()
