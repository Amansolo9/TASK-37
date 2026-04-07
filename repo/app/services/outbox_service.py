"""Outbox event service for offline webhook-style integrations."""

import json
from datetime import datetime
from flask import current_app
from app.extensions import db
from app.models.api import OutboxEvent


def create_event(topic, aggregate_type, aggregate_id, payload):
    event = OutboxEvent(
        topic=topic,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload_json=json.dumps(payload, default=str),
        status="pending",
        available_at=datetime.utcnow(),
    )
    db.session.add(event)
    db.session.commit()
    return event


def pull_events(consumer_name=None, limit=50):
    """Pull pending events. When consumer_name is given, claim them for that consumer."""
    q = OutboxEvent.query.filter_by(status="pending")
    if consumer_name:
        q = q.filter(
            db.or_(OutboxEvent.consumer_name == consumer_name, OutboxEvent.consumer_name.is_(None))
        )
    events = q.order_by(OutboxEvent.available_at).limit(limit).all()
    # Claim unclaimed events for this consumer
    if consumer_name:
        for e in events:
            if e.consumer_name is None:
                e.consumer_name = consumer_name
        db.session.commit()
    return events


def acknowledge_event(event_id, consumer_name=None):
    """Acknowledge an event. Requires the event to be claimed and consumer to match."""
    event = db.session.get(OutboxEvent, event_id)
    if not event:
        raise ValueError("Event not found.")
    if event.status == "delivered":
        raise ValueError("Event already acknowledged.")
    # Unclaimed events cannot be acknowledged directly — must be claimed first via pull
    if event.consumer_name is None:
        raise ValueError("Event is unclaimed. Pull events first to claim them.")
    # consumer_name is required and must match the claiming consumer
    if not consumer_name:
        raise ValueError("Consumer name is required for acknowledgment.")
    if event.consumer_name != consumer_name:
        raise ValueError("Event belongs to a different consumer.")
    event.status = "delivered"
    event.delivered_at = datetime.utcnow()
    db.session.commit()
    return event


def deliver_to_webhooks(event):
    """Attempt local webhook delivery if EXTERNAL_INTEGRATIONS_ENABLED."""
    if not current_app.config.get("EXTERNAL_INTEGRATIONS_ENABLED", False):
        return
    from app.models.api import WebhookSubscription
    subs = WebhookSubscription.query.filter_by(active=True).all()
    for sub in subs:
        if not sub.local_only:
            continue  # skip non-local endpoints when integrations enabled
        try:
            import urllib.request
            req = urllib.request.Request(
                sub.endpoint_url,
                data=event.payload_json.encode(),
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            event.attempts += 1
            event.last_error = str(e)
            db.session.commit()
