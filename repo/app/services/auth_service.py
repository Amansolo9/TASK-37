"""Authentication service with lockout and session management."""

from datetime import datetime, timedelta
from flask import current_app
from app.extensions import db
from app.models.user import User
from app.utils.auth_helpers import hash_password, verify_password
from app.services.audit_service import log_action


def authenticate_user(username, password):
    """Attempt login. Returns (user, error_message) tuple."""
    user = User.query.filter_by(username=username).first()
    if not user:
        return None, "Invalid username or password."

    if not user.is_active_user:
        return None, "Account is disabled."

    # Check lockout
    if user.lockout_until and user.lockout_until > datetime.utcnow():
        remaining = (user.lockout_until - datetime.utcnow()).seconds // 60 + 1
        log_action(user.id, "login_attempt_locked", "user", user.id)
        return None, f"Account locked. Try again in {remaining} minutes."

    if not verify_password(user.password_hash, password):
        user.failed_login_attempts += 1
        threshold = current_app.config["LOGIN_LOCKOUT_THRESHOLD"]
        if user.failed_login_attempts >= threshold:
            lockout_min = current_app.config["LOGIN_LOCKOUT_MINUTES"]
            user.lockout_until = datetime.utcnow() + timedelta(minutes=lockout_min)
            log_action(user.id, "account_locked", "user", user.id,
                      {"attempts": user.failed_login_attempts})
        db.session.commit()
        log_action(user.id, "login_failed", "user", user.id)
        return None, "Invalid username or password."

    # Success
    user.failed_login_attempts = 0
    user.lockout_until = None
    user.last_login_at = datetime.utcnow()
    user.last_activity_at = datetime.utcnow()
    db.session.commit()
    log_action(user.id, "login_success", "user", user.id)
    return user, None


def create_user(username, display_name, password, role_names=None):
    """Create a new user with optional roles."""
    from app.models.user import Role

    if not password or len(password.strip()) < 8:
        raise ValueError("Password must be at least 8 characters.")
    pw_hash = hash_password(password)
    user = User(
        username=username,
        display_name=display_name,
        password_hash=pw_hash,
        is_active_user=True,
        last_activity_at=datetime.utcnow(),
    )
    if role_names:
        roles = Role.query.filter(Role.name.in_(role_names)).all()
        user.roles = roles
    db.session.add(user)
    db.session.commit()
    return user


def change_password(user, new_password):
    user.password_hash = hash_password(new_password)
    db.session.commit()
    log_action(user.id, "password_changed", "user", user.id)
