"""Order and payment tests."""

import pytest
from decimal import Decimal
from app.services import order_service
from app.models.catalog import ServiceItem, Order


class TestOrderWorkflow:
    @pytest.fixture
    def service_item(self, db):
        si = ServiceItem(code="TST-001", name="Test Service", pricing_model="hourly",
                        unit_rate=Decimal("50.00"), taxable=True, active=True)
        db.session.add(si)
        db.session.commit()
        return si

    def test_create_order(self, app, db, admin_user, region, service_item):
        with app.app_context():
            order = order_service.create_order(
                customer_name="Test Corp", region_id=region.id, user_id=admin_user.id,
                line_items=[{"service_item_id": service_item.id, "quantity": 3}],
            )
            assert order.order_number.startswith("ORD-")
            assert order.subtotal_amount == Decimal("150.00")
            assert order.tax_amount > 0
            assert order.state == "created"

    def test_tax_calculation(self, app, db, admin_user, region, service_item):
        with app.app_context():
            order = order_service.create_order(
                customer_name="Tax Test", region_id=region.id, user_id=admin_user.id,
                line_items=[{"service_item_id": service_item.id, "quantity": 2}],
            )
            expected_sub = Decimal("100.00")
            expected_tax = (expected_sub * Decimal("0.0825")).quantize(Decimal("0.01"))
            assert order.subtotal_amount == expected_sub
            assert order.tax_amount == expected_tax
            assert order.total_amount == expected_sub + expected_tax

    def test_payment_and_transition(self, app, db, admin_user, region, service_item):
        with app.app_context():
            order = order_service.create_order(
                customer_name="Pay Test", region_id=region.id, user_id=admin_user.id,
                line_items=[{"service_item_id": service_item.id, "quantity": 1}],
            )
            order_service.record_payment(
                order.id, "cash", "RCP-001", order.total_amount, admin_user.id,
            )
            order_service.transition_order(order.id, "paid", admin_user.id)
            refreshed = db.session.get(Order, order.id)
            assert refreshed.state == "paid"

    def test_cannot_pay_without_payment(self, app, db, admin_user, region, service_item):
        with app.app_context():
            order = order_service.create_order(
                customer_name="NoPay", region_id=region.id, user_id=admin_user.id,
                line_items=[{"service_item_id": service_item.id, "quantity": 1}],
            )
            with pytest.raises(ValueError, match="payment record"):
                order_service.transition_order(order.id, "paid", admin_user.id)

    def test_invalid_transition(self, app, db, admin_user, region, service_item):
        with app.app_context():
            order = order_service.create_order(
                customer_name="BadTrans", region_id=region.id, user_id=admin_user.id,
                line_items=[{"service_item_id": service_item.id, "quantity": 1}],
            )
            with pytest.raises(ValueError, match="Cannot transition"):
                order_service.transition_order(order.id, "completed", admin_user.id)


class TestReconciliation:
    @pytest.fixture
    def paid_order(self, db, app, admin_user, region):
        si = ServiceItem(code="REC-001", name="Rec Svc", pricing_model="per_use",
                       unit_rate=Decimal("100.00"), taxable=True, active=True)
        db.session.add(si)
        db.session.commit()
        order = order_service.create_order(
            customer_name="RecTest", region_id=region.id, user_id=admin_user.id,
            line_items=[{"service_item_id": si.id, "quantity": 1}],
        )
        order_service.record_payment(order.id, "cash", "RCP-REC", order.total_amount, admin_user.id)
        order_service.transition_order(order.id, "paid", admin_user.id)
        return db.session.get(Order, order.id)

    def test_reconciliation_flags_delta(self, app, db, admin_user, paid_order):
        run = order_service.create_reconciliation_run(
            "Test Run", admin_user.id,
            [paid_order.id], [float(paid_order.total_amount) - 10.0],
        )
        assert len(run.items) == 1
        assert run.items[0].flagged_for_review is True
        assert abs(run.items[0].delta_amount) > Decimal("5.00")

    def test_reconciliation_match(self, app, db, admin_user, paid_order):
        run = order_service.create_reconciliation_run(
            "Match Run", admin_user.id,
            [paid_order.id], [float(paid_order.total_amount)],
        )
        assert run.items[0].flagged_for_review is False
