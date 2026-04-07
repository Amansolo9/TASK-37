"""Audit logging service."""

import json
from datetime import datetime
from app.extensions import db
from app.models.user import AuditLog


def log_action(actor_id, action, entity_type=None, entity_id=None, details=None):
    entry = AuditLog(
        actor_user_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details_json=json.dumps(details) if details else None,
        created_at=datetime.utcnow(),
    )
    db.session.add(entry)
    db.session.commit()
    return entry
