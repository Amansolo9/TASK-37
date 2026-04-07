"""Order management routes."""

from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from functools import wraps
from decimal import Decimal
from app.blueprints.orders import bp
from app.services import order_service
from app.models.catalog import ServiceItem, Order, ReconciliationRun, ReconciliationItem
from app.models.region import Region
from app.forms.order_forms import OrderForm, PaymentForm, ReconciliationForm
from app.utils.pagination import paginate_query
from app.utils.date_helpers import parse_date_us
from app.services.access_policy import apply_region_filter, check_region_access
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


@bp.route("")
@login_required
@permission_required("orders.manage")
def order_list():
    state = request.args.get("state")
    region_id = request.args.get("region_id", type=int)
    query = order_service.get_order_list(state=state, region_id=region_id)
    query = apply_region_filter(query, Order, current_user)
    pagination = paginate_query(query)
    regions = Region.query.filter_by(active=True).all()
    is_htmx = request.headers.get("HX-Request")
    template = "orders/order_list_partial.html" if is_htmx else "orders/order_list.html"
    return render_template(template, pagination=pagination, regions=regions,
                          current_state=state, current_region_id=region_id)


@bp.route("/new", methods=["GET", "POST"])
@login_required
@permission_required("orders.manage")
def order_new():
    form = OrderForm()
    form.region_id.choices = [(r.id, r.name) for r in Region.query.filter_by(active=True).all()]
    services = ServiceItem.query.filter_by(active=True).all()
    if form.validate_on_submit():
        sched_date = parse_date_us(form.scheduled_date.data)
        line_items = []
        for key in request.form:
            if key.startswith("line_svc_"):
                idx = key.split("_")[-1]
                svc_id = request.form.get(f"line_svc_{idx}", type=int)
                qty = request.form.get(f"line_qty_{idx}", type=float, default=1)
                if svc_id:
                    line_items.append({"service_item_id": svc_id, "quantity": qty})
        try:
            order = order_service.create_order(
                customer_name=form.customer_name.data,
                region_id=form.region_id.data,
                user_id=current_user.id,
                customer_org=form.customer_org.data,
                service_address=form.service_address.data,
                scheduled_date=sched_date,
                notes=form.notes.data,
                line_items=line_items,
            )
            flash(f"Order {order.order_number} created.", "success")
            return redirect(url_for("orders.order_detail", id=order.id))
        except ValueError as e:
            flash(str(e), "danger")
    return render_template("orders/order_form.html", form=form, services=services)


@bp.route("/<int:id>")
@login_required
@permission_required("orders.manage")
def order_detail(id):
    order = order_service.get_order_detail(id)
    if not order:
        flash("Order not found.", "danger")
        return redirect(url_for("orders.order_list"))
    if not check_region_access(order, current_user):
        flash("Access denied.", "danger")
        return redirect(url_for("orders.order_list"))
    address = None
    device_id = None
    credit_history = None
    if current_user.has_permission("analytics.view_financials"):
        address = order_service.get_decrypted_address(order)
        device_id = order_service.get_decrypted_device_identifier(order)
        credit_history = order_service.get_decrypted_credit_history(order)
    return render_template("orders/order_detail.html", order=order, address=address,
                          device_id=device_id, credit_history=credit_history)


@bp.route("/<int:id>/payments", methods=["GET", "POST"])
@login_required
@permission_required("orders.record_payment")
def payments(id):
    order = order_service.get_order_detail(id)
    if not order:
        flash("Order not found.", "danger")
        return redirect(url_for("orders.order_list"))
    if not check_region_access(order, current_user):
        flash("Access denied.", "danger")
        return redirect(url_for("orders.order_list"))
    form = PaymentForm()
    if form.validate_on_submit():
        try:
            order_service.record_payment(
                order_id=id, tender_type=form.tender_type.data,
                receipt_number=form.receipt_number.data,
                amount=form.amount.data, user_id=current_user.id,
                reference_note=form.reference_note.data,
            )
            flash("Payment recorded.", "success")
        except ValueError as e:
            flash(str(e), "danger")
        return redirect(url_for("orders.payments", id=id))
    return render_template("orders/payments.html", order=order, form=form)


@bp.route("/<int:id>/pay", methods=["POST"])
@login_required
@permission_required("orders.manage")
def mark_paid(id):
    order = order_service.get_order_detail(id)
    if not order or not check_region_access(order, current_user):
        flash("Access denied.", "danger")
        return redirect(url_for("orders.order_list"))
    try:
        order_service.transition_order(id, "paid", current_user.id)
        flash("Order marked as paid.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("orders.order_detail", id=id))


@bp.route("/<int:id>/complete", methods=["POST"])
@login_required
@permission_required("orders.manage")
def mark_completed(id):
    order = order_service.get_order_detail(id)
    if not order or not check_region_access(order, current_user):
        flash("Access denied.", "danger")
        return redirect(url_for("orders.order_list"))
    try:
        order_service.transition_order(id, "completed", current_user.id)
        flash("Order completed.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("orders.order_detail", id=id))


@bp.route("/<int:id>/cancel", methods=["POST"])
@login_required
@permission_required("orders.manage")
def cancel(id):
    order = order_service.get_order_detail(id)
    if not order or not check_region_access(order, current_user):
        flash("Access denied.", "danger")
        return redirect(url_for("orders.order_list"))
    try:
        order_service.transition_order(id, "canceled", current_user.id)
        flash("Order canceled.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("orders.order_detail", id=id))


@bp.route("/<int:id>/refund", methods=["POST"])
@login_required
@permission_required("orders.manage")
def refund(id):
    order = order_service.get_order_detail(id)
    if not order or not check_region_access(order, current_user):
        flash("Access denied.", "danger")
        return redirect(url_for("orders.order_list"))
    try:
        order_service.transition_order(id, "refunded", current_user.id)
        flash("Order refunded.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("orders.order_detail", id=id))


@bp.route("/reconciliation")
@login_required
@permission_required("orders.reconcile")
def reconciliation():
    runs = ReconciliationRun.query.order_by(ReconciliationRun.created_at.desc()).all()
    return render_template("orders/reconciliation.html", runs=runs)


@bp.route("/reconciliation/new", methods=["GET", "POST"])
@login_required
@permission_required("orders.reconcile")
def reconciliation_new():
    form = ReconciliationForm()
    if form.validate_on_submit():
        order_ids = [int(x) for x in request.form.getlist("order_ids")]
        actuals = [Decimal(x) for x in request.form.getlist("actual_amounts")]
        if len(order_ids) != len(actuals):
            flash("Mismatched order and amount counts.", "danger")
            return render_template("orders/reconciliation_form.html", form=form)
        run = order_service.create_reconciliation_run(
            form.label.data, current_user.id, order_ids, actuals, form.notes.data,
        )
        flash("Reconciliation run created.", "success")
        return redirect(url_for("orders.reconciliation"))
    paid_orders = Order.query.filter(Order.state.in_(["paid", "completed"])).all()
    return render_template("orders/reconciliation_form.html", form=form, orders=paid_orders)
