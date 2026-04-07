"""API client, usage, outbox, and webhook models."""

from datetime import datetime
from app.extensions import db


class ApiClient(db.Model):
    __tablename__ = "api_clients"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    key_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    secret_hash = db.Column(db.String(255), nullable=False)
    scopes_json = db.Column(db.Text, nullable=True)
    active = db.Column(db.Boolean, default=True, nullable=False)
    last_used_at = db.Column(db.DateTime, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    creator = db.relationship("User", foreign_keys=[created_by])


class ApiUsageCounter(db.Model):
    __tablename__ = "api_usage_counters"
    id = db.Column(db.Integer, primary_key=True)
    api_client_id = db.Column(db.Integer, db.ForeignKey("api_clients.id"), nullable=False)
    usage_date = db.Column(db.Date, nullable=False)
    request_count = db.Column(db.Integer, default=0, nullable=False)

    __table_args__ = (db.UniqueConstraint("api_client_id", "usage_date"),)


class OutboxEvent(db.Model):
    __tablename__ = "outbox_events"
    id = db.Column(db.Integer, primary_key=True)
    topic = db.Column(db.String(100), nullable=False, index=True)
    aggregate_type = db.Column(db.String(80), nullable=False)
    aggregate_id = db.Column(db.Integer, nullable=False)
    payload_json = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default="pending", nullable=False, index=True)
    available_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    delivered_at = db.Column(db.DateTime, nullable=True)
    attempts = db.Column(db.Integer, default=0, nullable=False)
    last_error = db.Column(db.Text, nullable=True)
    consumer_name = db.Column(db.String(100), nullable=True)


class WebhookSubscription(db.Model):
    __tablename__ = "webhook_subscriptions"
    id = db.Column(db.Integer, primary_key=True)
    consumer_name = db.Column(db.String(100), nullable=False)
    endpoint_url = db.Column(db.String(500), nullable=False)
    secret = db.Column(db.String(255), nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    local_only = db.Column(db.Boolean, default=True, nullable=False)
