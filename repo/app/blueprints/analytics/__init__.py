"""Analytics blueprint."""

from flask import Blueprint

bp = Blueprint("analytics", __name__, template_folder="../../templates/analytics")

from app.blueprints.analytics import routes  # noqa
