"""Scheduling and resource management models."""

from datetime import datetime
from app.extensions import db


class Resource(db.Model):
    __tablename__ = "resources"
    id = db.Column(db.Integer, primary_key=True)
    resource_type = db.Column(db.String(50), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    code = db.Column(db.String(50), unique=True, nullable=False)
    region_id = db.Column(db.Integer, db.ForeignKey("regions.id"), nullable=True)
    active = db.Column(db.Boolean, default=True, nullable=False)
    metadata_json = db.Column(db.Text, nullable=True)

    region = db.relationship("Region", foreign_keys=[region_id])
    availability = db.relationship("ResourceAvailability", backref="resource", cascade="all, delete-orphan")


class ResourceAvailability(db.Model):
    __tablename__ = "resource_availability"
    id = db.Column(db.Integer, primary_key=True)
    resource_id = db.Column(db.Integer, db.ForeignKey("resources.id"), nullable=False, index=True)
    day_of_week = db.Column(db.Integer, nullable=False)  # 0=Mon ... 6=Sun
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    effective_from = db.Column(db.Date, nullable=True)
    effective_to = db.Column(db.Date, nullable=True)


class TimeSlotTemplate(db.Model):
    __tablename__ = "time_slot_templates"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    region_id = db.Column(db.Integer, db.ForeignKey("regions.id"), nullable=True)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)

    region = db.relationship("Region", foreign_keys=[region_id])


class ScheduleItem(db.Model):
    __tablename__ = "schedule_items"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    region_id = db.Column(db.Integer, db.ForeignKey("regions.id"), nullable=False)
    scheduled_date = db.Column(db.Date, nullable=False, index=True)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    classroom_id = db.Column(db.Integer, db.ForeignKey("resources.id"), nullable=True)
    instructor_id = db.Column(db.Integer, db.ForeignKey("resources.id"), nullable=True)
    time_slot_template_id = db.Column(db.Integer, db.ForeignKey("time_slot_templates.id"), nullable=True)
    status = db.Column(db.String(20), default="draft", nullable=False, index=True)
    source_order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    region = db.relationship("Region", foreign_keys=[region_id])
    classroom = db.relationship("Resource", foreign_keys=[classroom_id])
    instructor = db.relationship("Resource", foreign_keys=[instructor_id])
    time_slot_template = db.relationship("TimeSlotTemplate", foreign_keys=[time_slot_template_id])
    creator = db.relationship("User", foreign_keys=[created_by])
    updater = db.relationship("User", foreign_keys=[updated_by])
    conflicts = db.relationship("ScheduleConflict", backref="schedule_item", foreign_keys="ScheduleConflict.schedule_item_id")
    changes = db.relationship("ScheduleChange", backref="schedule_item", order_by="ScheduleChange.changed_at.desc()")


class ScheduleConflict(db.Model):
    __tablename__ = "schedule_conflicts"
    id = db.Column(db.Integer, primary_key=True)
    schedule_item_id = db.Column(db.Integer, db.ForeignKey("schedule_items.id"), nullable=False, index=True)
    conflict_type = db.Column(db.String(50), nullable=False)
    related_schedule_item_id = db.Column(db.Integer, db.ForeignKey("schedule_items.id"), nullable=True)
    related_resource_id = db.Column(db.Integer, db.ForeignKey("resources.id"), nullable=True)
    severity = db.Column(db.String(20), default="error", nullable=False)
    message = db.Column(db.Text, nullable=False)
    resolved_at = db.Column(db.DateTime, nullable=True)
    resolved_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    related_item = db.relationship("ScheduleItem", foreign_keys=[related_schedule_item_id])
    related_resource = db.relationship("Resource", foreign_keys=[related_resource_id])


class ScheduleChange(db.Model):
    __tablename__ = "schedule_changes"
    id = db.Column(db.Integer, primary_key=True)
    schedule_item_id = db.Column(db.Integer, db.ForeignKey("schedule_items.id"), nullable=False, index=True)
    change_type = db.Column(db.String(50), nullable=False)
    old_values_json = db.Column(db.Text, nullable=True)
    new_values_json = db.Column(db.Text, nullable=True)
    notice_text = db.Column(db.Text, nullable=True)
    changed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    changed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    changer = db.relationship("User", foreign_keys=[changed_by])
