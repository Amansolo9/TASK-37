"""CMS blueprint."""

from flask import Blueprint

bp = Blueprint("cms", __name__, template_folder="../../templates/cms")

from app.blueprints.cms import routes  # noqa
