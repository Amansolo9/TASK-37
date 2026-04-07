"""Unified principal resolution for browser sessions and API JWT contexts."""

from flask import g
from flask_login import current_user


def get_current_actor_id():
    """Return the acting user ID from either browser session or API JWT context.

    For browser routes: returns current_user.id from Flask-Login session.
    For API routes: returns the api_client_id stored in g by jwt_required decorator.

    Raises RuntimeError if no authenticated principal is available.
    """
    # Browser session
    if current_user and hasattr(current_user, 'id') and current_user.is_authenticated:
        return current_user.id
    # API JWT context (api_client_id is the ApiClient.id, which maps to created_by user)
    api_client_id = g.get("api_client_id")
    if api_client_id:
        return _resolve_api_actor(api_client_id)
    raise RuntimeError("No authenticated principal available")


def _resolve_api_actor(api_client_id):
    """Resolve the user identity behind an API client."""
    from app.models.api import ApiClient
    from app.extensions import db
    client = db.session.get(ApiClient, api_client_id)
    if client and client.created_by:
        return client.created_by
    # Fallback: return the client ID itself as actor (still traceable)
    return api_client_id


def get_api_scopes():
    """Return the scopes from the current API JWT context, or empty set."""
    return set(g.get("api_scopes", []))


def has_api_scope(scope):
    """Check if the current API context has a given scope."""
    return scope in get_api_scopes()


def is_safe_redirect_url(target):
    """Validate that a redirect target is a safe internal relative URL."""
    if not target:
        return False
    # Block absolute URLs, protocol-relative URLs, and javascript: schemes
    if target.startswith(("http://", "https://", "//", "javascript:")):
        return False
    # Must start with /
    if not target.startswith("/"):
        return False
    # Block backslash tricks
    if "\\" in target:
        return False
    return True
