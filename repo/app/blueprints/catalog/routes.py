"""Service catalog routes."""

from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from functools import wraps
from app.blueprints.catalog import bp
from app.models.catalog import ServiceItem
from app.forms.catalog_forms import ServiceItemForm
from app.extensions import db


def permission_required(*perms):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not current_user.has_any_permission(*perms):
                flash("Permission denied.", "danger")
                return redirect(url_for("dashboard"))
            return f(*args, **kwargs)
        return decorated
    return decorator


@bp.route("/services")
@login_required
@permission_required("orders.manage")
def services():
    items = ServiceItem.query.order_by(ServiceItem.name).all()
    return render_template("catalog/services.html", services=items)


@bp.route("/services/new", methods=["GET", "POST"])
@login_required
@permission_required("orders.manage")
def service_new():
    form = ServiceItemForm()
    if form.validate_on_submit():
        svc = ServiceItem(
            code=form.code.data, name=form.name.data,
            description=form.description.data,
            pricing_model=form.pricing_model.data,
            unit_rate=form.unit_rate.data,
            package_price=form.package_price.data,
            cost_amount=form.cost_amount.data,
            taxable=form.taxable.data, active=True,
        )
        db.session.add(svc)
        db.session.commit()
        flash("Service item created.", "success")
        return redirect(url_for("catalog.services"))
    return render_template("catalog/service_form.html", form=form)


@bp.route("/services/<int:id>", methods=["GET", "POST"])
@login_required
@permission_required("orders.manage")
def service_edit(id):
    svc = db.session.get(ServiceItem, id)
    if not svc:
        flash("Service not found.", "danger")
        return redirect(url_for("catalog.services"))
    form = ServiceItemForm(obj=svc)
    if form.validate_on_submit():
        svc.code = form.code.data
        svc.name = form.name.data
        svc.description = form.description.data
        svc.pricing_model = form.pricing_model.data
        svc.unit_rate = form.unit_rate.data
        svc.package_price = form.package_price.data
        svc.cost_amount = form.cost_amount.data
        svc.taxable = form.taxable.data
        db.session.commit()
        flash("Service updated.", "success")
        return redirect(url_for("catalog.services"))
    return render_template("catalog/service_form.html", form=form, editing=True, service=svc)
