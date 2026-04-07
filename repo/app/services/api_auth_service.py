"""API JWT authentication and quota enforcement."""

import json
import jwt
from datetime import datetime, date, timedelta
from flask import current_app
from app.extensions import db
from app.models.api import ApiClient, ApiUsageCounter
from app.utils.auth_helpers import hash_password, verify_password
from app.services.audit_service import log_action


def authenticate_api_client(key_id, secret):
    client = ApiClient.query.filter_by(key_id=key_id, active=True).first()
    if not client:
        return None, "Invalid credentials."
    if not verify_password(client.secret_hash, secret):
        return None, "Invalid credentials."
    client.last_used_at = datetime.utcnow()
    db.session.commit()
    return client, None


def generate_jwt(client):
    scopes = json.loads(client.scopes_json) if client.scopes_json else []
    payload = {
        "sub": client.key_id,
        "client_id": client.id,
        "scopes": scopes,
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(
            seconds=current_app.config.get("JWT_ACCESS_TOKEN_EXPIRES_SECONDS", 3600)
        ),
    }
    token = jwt.encode(payload, current_app.config["JWT_SECRET_KEY"], algorithm="HS256")
    return token


def decode_jwt(token):
    try:
        payload = jwt.decode(token, current_app.config["JWT_SECRET_KEY"], algorithms=["HS256"])
        return payload, None
    except jwt.ExpiredSignatureError:
        return None, "Token expired."
    except jwt.InvalidTokenError:
        return None, "Invalid token."


def check_quota(client_id):
    today = date.today()
    counter = ApiUsageCounter.query.filter_by(
        api_client_id=client_id, usage_date=today
    ).first()
    if not counter:
        counter = ApiUsageCounter(api_client_id=client_id, usage_date=today, request_count=0)
        db.session.add(counter)
        db.session.flush()

    quota = current_app.config.get("API_DAILY_QUOTA", 1000)
    if counter.request_count >= quota:
        return False, counter.request_count
    counter.request_count += 1
    db.session.commit()
    return True, counter.request_count


def create_api_client(name, scopes, creator_id):
    import secrets
    key_id = secrets.token_hex(16)
    raw_secret = secrets.token_hex(32)
    secret_hash = hash_password(raw_secret)
    client = ApiClient(
        name=name, key_id=key_id, secret_hash=secret_hash,
        scopes_json=json.dumps(scopes), active=True, created_by=creator_id,
    )
    db.session.add(client)
    db.session.commit()
    log_action(creator_id, "api_client_created", "api_client", client.id)
    return client, raw_secret
