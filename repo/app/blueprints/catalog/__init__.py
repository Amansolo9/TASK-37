"""Catalog blueprint."""

from flask import Blueprint

bp = Blueprint("catalog", __name__, template_folder="../../templates/catalog")

from app.blueprints.catalog import routes  # noqa
