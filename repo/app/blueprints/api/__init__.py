"""API blueprint for REST and GraphQL endpoints."""

from flask import Blueprint

bp = Blueprint("api", __name__)

from app.blueprints.api import routes  # noqa
