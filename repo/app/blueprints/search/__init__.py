"""Search blueprint."""

from flask import Blueprint

bp = Blueprint("search", __name__, template_folder="../../templates/search")

from app.blueprints.search import routes  # noqa
