"""Ticket sales, the organizer's side: the payout account and the ticket panel.

Ways these services could fail, each pinned below:

Payout account
- Connecting twice opens a second Stripe account instead of resuming the first.
- Resuming onboarding for a sphere that never connected sends it somewhere.
- Coming back from onboarding shows the stale state Stripe has since changed.

Panel
- Archived types are priced as if on sale, or vanish from the panel.
- The takings count unpaid or refunded orders.
- The order list hides that older orders were left out.
- A ticket type or order of another event is read, changed or refunded.
- An unpaid order is refunded, or Stripe refusing a refund records one anyway.
"""

from decimal import Decimal

import pytest

from ludamus.pacts.legacy import NotFoundError
from ludamus.pacts.payment_api import CheckoutStage, RefundEvent, WebhookOutcome
from ludamus.pacts.tickets import (
    OrderStatus,
    PayoutPageDTO,
    PayoutStatus,
    RefundOutcome,
    TicketSalesSummaryDTO,
)
from ludamus.specs.tickets import PANEL_ORDERS_SHOWN
from tests.unit.ticket_fakes import (
    ACCOUNT_ID,
    BUYER_ID,
    EVENT_ID,
    OTHER_EVENT_ID,
    PRICE,
    SPHERE_ID,
    add_order,
    checkout_event,
    deliver,
)

pytest_plugins = ("tests.unit.ticket_fixtures",)

# Two tickets at 50 zł: 3.5% of 100 zł, and Stripe's 2.9% + 0.30 zł estimate.
_TWO_TICKETS = 10_000
_FEE_ON_TWO = 350
_STRIPE_FEE_ON_TWO = 320
_FEE_PERCENT = Decimal("3.5")
_DEAL_FEE_BPS = 150
# 1.5% of 100 zł.
_DEAL_FEE_ON_TWO = 150


class TestPayoutService:
    def test_unconnected_sphere_has_no_payouts(self, payout):
        assert payout.page(sphere_id=SPHERE_ID) == PayoutPageDTO(
            status=PayoutStatus.NOT_CONNECTED, available=True, payouts_enabled=False
        )

    def test_connecting_opens_one_account_and_resumes_it_after(self, payout, accounts):
        first = payout.onboarding_url(
            sphere_id=SPHERE_ID,
            email="org@example.com",
            refresh_url="/refresh/",
            return_url="/return/",
        )
        again = payout.onboarding_url(
            sphere_id=SPHERE_ID,
            email="org@example.com",
            refresh_url="/refresh/",
            return_url="/return/",
        )

        assert first == again == "https://connect.stripe.test/acct_new_1"
        assert [account.stripe_account_id for account in accounts.rows.values()] == [
            "acct_new_1"
        ]
        assert payout.page(sphere_id=SPHERE_ID).status is PayoutStatus.INCOMPLETE

    def test_resuming_onboarding_without_an_account_goes_nowhere(self, payout):
        assert (
            payout.resume_onboarding_url(
                sphere_id=SPHERE_ID, refresh_url="/refresh/", return_url="/return/"
            )
            is None
        )

    def test_resuming_onboarding_returns_to_the_connected_account(
        self, payout, accounts
    ):
        accounts.add(charges_enabled=False)

        assert (
            payout.resume_onboarding_url(
                sphere_id=SPHERE_ID, refresh_url="/refresh/", return_url="/return/"
            )
            == f"https://connect.stripe.test/{ACCOUNT_ID}"
        )

    def test_refresh_reads_the_account_state_back_from_stripe(self, payout, accounts):
        accounts.add(
            details_submitted=False, charges_enabled=False, payouts_enabled=False
        )

        assert payout.refresh(sphere_id=SPHERE_ID) == PayoutPageDTO(
            status=PayoutStatus.ACTIVE, available=True, payouts_enabled=True
        )

    def test_refresh_without_an_account_stays_unconnected(self, payout, accounts):
        assert payout.refresh(sphere_id=SPHERE_ID).status is (
            PayoutStatus.NOT_CONNECTED
        )
        assert accounts.rows == {}


class TestPanel:
    def test_page_prices_live_types_and_totals_only_paid_orders(
        self, panel, types, orders, accounts
    ):
        accounts.add(charges_enabled=False)
        on_sale = types.add(price=PRICE)
        retired = types.add(is_archived=True)
        types.add(event_id=OTHER_EVENT_ID)
        paid = add_order(
            orders, on_sale, status=OrderStatus.PAID, platform_fee=_FEE_ON_TWO
        )
        refunded = add_order(orders, on_sale, status=OrderStatus.REFUNDED)
        add_order(orders, on_sale, status=OrderStatus.EXPIRED)
        add_order(orders, on_sale, status=OrderStatus.PAID, event_id=OTHER_EVENT_ID)

        page = panel.page(sphere_id=SPHERE_ID, event_id=EVENT_ID)

        assert page.payout_status is PayoutStatus.INCOMPLETE
        assert page.payments_available
        assert page.platform_fee_percent == _FEE_PERCENT
        assert [row.ticket_type.pk for row in page.rows] == [on_sale.pk]
        assert page.rows[0].fees.platform_fee == _FEE_ON_TWO // 2
        assert [ticket_type.pk for ticket_type in page.archived] == [retired.pk]
        assert page.summary == TicketSalesSummaryDTO(
            orders=1,
            tickets=paid.ticket_count,
            gross=_TWO_TICKETS,
            platform_fees=_FEE_ON_TWO,
            estimated_stripe_fees=_STRIPE_FEE_ON_TWO,
        )
        assert [row.pk for row in page.orders] == [refunded.pk, paid.pk]
        assert not page.more_orders

    def test_page_prices_at_the_spheres_deal_rate(self, panel, types, plans):
        plans.add(ticket_fee_bps=_DEAL_FEE_BPS)
        types.add(price=PRICE)

        page = panel.page(sphere_id=SPHERE_ID, event_id=EVENT_ID)

        assert page.platform_fee_percent == Decimal("1.5")
        assert page.rows[0].fees.platform_fee == _DEAL_FEE_ON_TWO // 2

    def test_page_says_when_older_orders_were_left_out(self, panel, types, orders):
        regular = types.add()
        for _ in range(PANEL_ORDERS_SHOWN + 1):
            add_order(orders, regular, status=OrderStatus.PAID)

        page = panel.page(sphere_id=SPHERE_ID, event_id=EVENT_ID)

        assert len(page.orders) == PANEL_ORDERS_SHOWN
        assert page.orders[0].pk == PANEL_ORDERS_SHOWN + 1
        assert page.more_orders

    def test_type_of_another_event_is_not_found(self, panel, book, types):
        foreign = types.add(event_id=OTHER_EVENT_ID)
        data = {
            "name": "Renamed",
            "description": "",
            "price": PRICE,
            "quantity": None,
            "sales_start": None,
            "sales_end": None,
        }

        with pytest.raises(NotFoundError):
            panel.read_type(event_id=EVENT_ID, pk=foreign.pk)
        with pytest.raises(NotFoundError):
            panel.update_type(event_id=EVENT_ID, pk=foreign.pk, data=data)
        with pytest.raises(NotFoundError):
            panel.set_archived(event_id=EVENT_ID, pk=foreign.pk, archived=True)
        assert book.types[foreign.pk] == foreign

    def test_created_type_goes_last_and_can_be_edited_and_archived(self, panel, types):
        first = types.add()
        data = {
            "name": "Weekend pass",
            "description": "Both days",
            "price": PRICE,
            "quantity": 100,
            "sales_start": None,
            "sales_end": None,
        }

        created = panel.create_type(event_id=EVENT_ID, data=data)
        panel.update_type(
            event_id=EVENT_ID, pk=created.pk, data=data | {"name": "Full pass"}
        )
        panel.set_archived(event_id=EVENT_ID, pk=created.pk, archived=True)

        stored = panel.read_type(event_id=EVENT_ID, pk=created.pk)
        assert created.order == first.order + 1
        assert created.currency == "pln"
        assert stored.name == "Full pass"
        assert stored.is_archived

    def test_order_of_another_event_is_not_refunded(
        self, panel, book, types, orders, payments
    ):
        foreign = add_order(
            orders,
            types.add(),
            event_id=OTHER_EVENT_ID,
            status=OrderStatus.PAID,
            stripe_payment_intent_id="pi_1",
        )

        with pytest.raises(NotFoundError):
            panel.refund(event_id=EVENT_ID, order_pk=foreign.pk)
        assert book.orders[foreign.pk] == foreign
        assert payments.refunded == []

    @pytest.mark.parametrize(
        ("status", "payment_intent_id"),
        ((OrderStatus.PENDING, "pi_1"), (OrderStatus.PAID, "")),
    )
    def test_order_without_a_settled_payment_is_not_refundable(
        self, panel, book, types, orders, payments, status, payment_intent_id
    ):
        order = add_order(
            orders,
            types.add(),
            status=status,
            stripe_payment_intent_id=payment_intent_id,
        )

        outcome = panel.refund(event_id=EVENT_ID, order_pk=order.pk)

        assert outcome is RefundOutcome.NOT_REFUNDABLE
        assert book.orders[order.pk] == order
        assert payments.refunded == []

    def test_refund_stripe_refuses_records_nothing(
        self, panel, book, types, orders, payments
    ):
        order = add_order(
            orders,
            types.add(),
            status=OrderStatus.PAID,
            stripe_payment_intent_id="pi_1",
        )
        payments.down.add("refund")

        outcome = panel.refund(event_id=EVENT_ID, order_pk=order.pk)

        assert outcome is RefundOutcome.PROVIDER_ERROR
        assert book.orders[order.pk] == order

    def test_refund_returns_the_money_and_voids_the_tickets(
        self, panel, sales, book, types, orders, payments
    ):
        order = add_order(orders, types.add(), stripe_checkout_session_id="cs_1")
        deliver(sales, payments, checkout_event(CheckoutStage.COMPLETED))

        outcome = panel.refund(event_id=EVENT_ID, order_pk=order.pk)
        webhook = deliver(
            sales, payments, RefundEvent(payment_intent_id="pi_1", fully_refunded=True)
        )

        assert outcome is RefundOutcome.REFUNDED
        assert webhook is WebhookOutcome.STALE
        assert payments.refunded == ["pi_1"]
        refunded = book.orders[order.pk]
        assert refunded.status is OrderStatus.REFUNDED
        assert sales.owned_tickets(sphere_id=SPHERE_ID, holder_id=BUYER_ID) == []
