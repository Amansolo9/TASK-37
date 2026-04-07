"""HTMX partial API blueprint.

Session-authenticated, CSRF-protected (not exempt).
Serves HTML partials for HTMX interactions via the service layer.
"""

from flask import Blueprint

bp = Blueprint("htmx_api", __name__)

from app.blueprints.htmx import routes  # noqa
