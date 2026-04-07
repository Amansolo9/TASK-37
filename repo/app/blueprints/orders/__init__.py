"""Orders blueprint."""

from flask import Blueprint

bp = Blueprint("orders", __name__, template_folder="../../templates/orders")

from app.blueprints.orders import routes  # noqa
