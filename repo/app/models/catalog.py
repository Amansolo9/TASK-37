"""Service catalog and order models."""

from datetime import datetime
from decimal import Decimal
from app.extensions import db


class ServiceItem(db.Model):
    __tablename__ = "service_items"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    pricing_model = db.Column(db.String(20), nullable=False)  # hourly, per_use, package
    unit_rate = db.Column(db.Numeric(10, 2), nullable=True)
    package_price = db.Column(db.Numeric(10, 2), nullable=True)
    cost_amount = db.Column(db.Numeric(10, 2), nullable=True)
    taxable = db.Column(db.Boolean, default=True, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    metadata_json = db.Column(db.Text, nullable=True)


class Order(db.Model):
    __tablename__ = "orders"
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    customer_name = db.Column(db.String(200), nullable=False)
    customer_org = db.Column(db.String(200), nullable=True)
    encrypted_service_address = db.Column(db.Text, nullable=True)
    encrypted_device_identifier = db.Column(db.Text, nullable=True)
    encrypted_credit_history = db.Column(db.Text, nullable=True)
    region_id = db.Column(db.Integer, db.ForeignKey("regions.id"), nullable=False)
    state = db.Column(db.String(20), default="created", nullable=False, index=True)
    scheduled_date = db.Column(db.Date, nullable=True)
    subtotal_amount = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    tax_rate = db.Column(db.Numeric(6, 4), default=0, nullable=False)
    tax_amount = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    total_amount = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    paid_amount = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    reconciliation_status = db.Column(db.String(20), nullable=True)
    reconciliation_delta = db.Column(db.Numeric(12, 2), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    paid_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    canceled_at = db.Column(db.DateTime, nullable=True)
    refunded_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    region = db.relationship("Region", foreign_keys=[region_id])
    creator = db.relationship("User", foreign_keys=[created_by])
    updater = db.relationship("User", foreign_keys=[updated_by])
    items = db.relationship("OrderItem", backref="order", cascade="all, delete-orphan")
    payments = db.relationship("Payment", backref="order", cascade="all, delete-orphan")


class OrderItem(db.Model):
    __tablename__ = "order_items"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False, index=True)
    service_item_id = db.Column(db.Integer, db.ForeignKey("service_items.id"), nullable=False)
    description_snapshot = db.Column(db.String(300), nullable=False)
    quantity = db.Column(db.Numeric(10, 2), default=1, nullable=False)
    unit_rate = db.Column(db.Numeric(10, 2), nullable=False)
    line_subtotal = db.Column(db.Numeric(12, 2), nullable=False)
    taxable = db.Column(db.Boolean, default=True, nullable=False)
    metadata_json = db.Column(db.Text, nullable=True)

    service_item = db.relationship("ServiceItem", foreign_keys=[service_item_id])


class Payment(db.Model):
    __tablename__ = "payments"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False, index=True)
    tender_type = db.Column(db.String(20), nullable=False)  # cash, check, invoice
    receipt_number = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    reference_note = db.Column(db.String(300), nullable=True)
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    recorder = db.relationship("User", foreign_keys=[recorded_by])


class ReconciliationRun(db.Model):
    __tablename__ = "reconciliation_runs"
    id = db.Column(db.Integer, primary_key=True)
    run_label = db.Column(db.String(200), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    notes = db.Column(db.Text, nullable=True)

    creator = db.relationship("User", foreign_keys=[created_by])
    items = db.relationship("ReconciliationItem", backref="run", cascade="all, delete-orphan")


class ReconciliationItem(db.Model):
    __tablename__ = "reconciliation_items"
    id = db.Column(db.Integer, primary_key=True)
    reconciliation_run_id = db.Column(db.Integer, db.ForeignKey("reconciliation_runs.id"), nullable=False, index=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False)
    expected_amount = db.Column(db.Numeric(12, 2), nullable=False)
    actual_amount = db.Column(db.Numeric(12, 2), nullable=False)
    delta_amount = db.Column(db.Numeric(12, 2), nullable=False)
    flagged_for_review = db.Column(db.Boolean, default=False, nullable=False)
    status = db.Column(db.String(20), default="pending", nullable=False)

    order = db.relationship("Order", foreign_keys=[order_id])
