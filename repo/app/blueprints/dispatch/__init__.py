"""Dispatch blueprint."""

from flask import Blueprint

bp = Blueprint("dispatch", __name__, template_folder="../../templates/dispatch")

from app.blueprints.dispatch import routes  # noqa
