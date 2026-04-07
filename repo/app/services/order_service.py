"""Order lifecycle service with pricing, payments, and reconciliation."""

import json
import uuid
from datetime import datetime
from decimal import Decimal
from app.extensions import db
from app.models.catalog import (
    ServiceItem, Order, OrderItem, Payment,
    ReconciliationRun, ReconciliationItem,
)
from app.models.region import Region
from app.services.audit_service import log_action
from app.utils.encryption import encrypt_value, decrypt_value

ORDER_STATES = {"created", "paid", "completed", "canceled", "refunded"}
ORDER_TRANSITIONS = {
    "created": ["paid", "canceled"],
    "paid": ["completed", "refunded"],
    "completed": ["refunded"],
}
RECONCILIATION_THRESHOLD = Decimal("5.00")


def generate_order_number():
    return f"ORD-{uuid.uuid4().hex[:8].upper()}"


def create_order(customer_name, region_id, user_id, customer_org=None,
                 service_address=None, scheduled_date=None, notes=None, line_items=None,
                 device_identifier=None, credit_history=None):
    region = db.session.get(Region, region_id)
    if not region:
        raise ValueError("Invalid region.")

    encrypted_addr = encrypt_value(service_address) if service_address else None
    encrypted_device_id = encrypt_value(device_identifier) if device_identifier else None
    encrypted_credit = encrypt_value(credit_history) if credit_history else None

    order = Order(
        order_number=generate_order_number(),
        customer_name=customer_name,
        customer_org=customer_org,
        encrypted_service_address=encrypted_addr,
        encrypted_device_identifier=encrypted_device_id,
        encrypted_credit_history=encrypted_credit,
        region_id=region_id,
        state="created",
        scheduled_date=scheduled_date,
        tax_rate=region.sales_tax_rate or Decimal("0"),
        created_by=user_id,
        updated_by=user_id,
        notes=notes,
    )
    db.session.add(order)
    db.session.flush()

    subtotal = Decimal("0")
    if line_items:
        for li in line_items:
            svc = db.session.get(ServiceItem, li["service_item_id"])
            if not svc:
                continue
            qty = Decimal(str(li.get("quantity", 1)))
            if svc.pricing_model == "hourly":
                unit_rate = svc.unit_rate or Decimal("0")
                line_sub = qty * unit_rate
            elif svc.pricing_model == "per_use":
                unit_rate = svc.unit_rate or Decimal("0")
                line_sub = qty * unit_rate
            elif svc.pricing_model == "package":
                unit_rate = svc.package_price or Decimal("0")
                line_sub = unit_rate * qty
            else:
                unit_rate = Decimal("0")
                line_sub = Decimal("0")

            oi = OrderItem(
                order_id=order.id,
                service_item_id=svc.id,
                description_snapshot=svc.name,
                quantity=qty,
                unit_rate=unit_rate,
                line_subtotal=line_sub,
                taxable=svc.taxable,
            )
            db.session.add(oi)
            subtotal += line_sub

    tax_amount = Decimal("0")
    taxable_subtotal = sum(
        oi.line_subtotal for oi in order.items if oi.taxable
    ) if order.items else subtotal
    if order.tax_rate:
        tax_amount = (taxable_subtotal * order.tax_rate).quantize(Decimal("0.01"))

    order.subtotal_amount = subtotal
    order.tax_amount = tax_amount
    order.total_amount = subtotal + tax_amount
    db.session.commit()
    log_action(user_id, "order_created", "order", order.id)
    return order


def recalculate_order(order):
    subtotal = sum(oi.line_subtotal for oi in order.items)
    taxable_subtotal = sum(oi.line_subtotal for oi in order.items if oi.taxable)
    tax_amount = (taxable_subtotal * order.tax_rate).quantize(Decimal("0.01")) if order.tax_rate else Decimal("0")
    order.subtotal_amount = subtotal
    order.tax_amount = tax_amount
    order.total_amount = subtotal + tax_amount
    db.session.commit()


def record_payment(order_id, tender_type, receipt_number, amount, user_id, reference_note=None):
    order = db.session.get(Order, order_id)
    if not order:
        raise ValueError("Order not found.")
    if tender_type not in ("cash", "check", "invoice"):
        raise ValueError("Invalid tender type.")
    if not receipt_number:
        raise ValueError("Receipt number is required.")

    payment = Payment(
        order_id=order.id,
        tender_type=tender_type,
        receipt_number=receipt_number,
        amount=Decimal(str(amount)),
        reference_note=reference_note,
        recorded_by=user_id,
    )
    db.session.add(payment)
    order.paid_amount += payment.amount
    db.session.commit()
    # Mask sensitive payment metadata in audit log
    masked_receipt = receipt_number[:3] + "***" if len(receipt_number) > 3 else "***"
    log_action(user_id, "payment_recorded", "order", order.id,
              {"tender_type": tender_type, "receipt": masked_receipt})
    return payment


def transition_order(order_id, new_state, user_id):
    order = db.session.get(Order, order_id)
    if not order:
        raise ValueError("Order not found.")
    if new_state not in ORDER_TRANSITIONS.get(order.state, []):
        raise ValueError(f"Cannot transition from {order.state} to {new_state}.")

    if new_state == "paid":
        if not order.payments:
            raise ValueError("At least one payment record required to mark as paid.")

    now = datetime.utcnow()
    order.state = new_state
    order.updated_by = user_id
    if new_state == "paid":
        order.paid_at = now
    elif new_state == "completed":
        order.completed_at = now
    elif new_state == "canceled":
        order.canceled_at = now
    elif new_state == "refunded":
        order.refunded_at = now

    db.session.commit()
    log_action(user_id, f"order_{new_state}", "order", order.id)

    try:
        from app.services.outbox_service import create_event
        create_event(f"order.{new_state}", "order", order.id, {"state": new_state})
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Outbox event failed for order %s state=%s: %s", order.id, new_state, e)
    return order


def create_reconciliation_run(label, user_id, order_ids, actual_amounts, notes=None):
    run = ReconciliationRun(run_label=label, created_by=user_id, notes=notes)
    db.session.add(run)
    db.session.flush()

    for order_id, actual in zip(order_ids, actual_amounts):
        order = db.session.get(Order, order_id)
        if not order:
            continue
        expected = order.total_amount
        actual_dec = Decimal(str(actual))
        delta = actual_dec - expected
        flagged = abs(delta) > RECONCILIATION_THRESHOLD

        ri = ReconciliationItem(
            reconciliation_run_id=run.id,
            order_id=order_id,
            expected_amount=expected,
            actual_amount=actual_dec,
            delta_amount=delta,
            flagged_for_review=flagged,
            status="flagged" if flagged else "matched",
        )
        db.session.add(ri)

        order.reconciliation_status = "flagged" if flagged else "matched"
        order.reconciliation_delta = delta

    db.session.commit()
    log_action(user_id, "reconciliation_run_created", "reconciliation_run", run.id)
    return run


def get_order_list(state=None, region_id=None):
    q = Order.query
    if state:
        q = q.filter(Order.state == state)
    if region_id:
        q = q.filter(Order.region_id == region_id)
    return q.order_by(Order.created_at.desc())


def get_order_detail(order_id):
    return db.session.get(Order, order_id)


def get_decrypted_address(order):
    return decrypt_value(order.encrypted_service_address) if order.encrypted_service_address else None


def get_decrypted_device_identifier(order):
    return decrypt_value(order.encrypted_device_identifier) if order.encrypted_device_identifier else None


def get_decrypted_credit_history(order):
    return decrypt_value(order.encrypted_credit_history) if order.encrypted_credit_history else None
