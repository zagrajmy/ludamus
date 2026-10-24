"""Ticket sales: the shop, and starting a checkout.

Ways the service could fail, each pinned below:

Shop
- A free event (no ticket types) reports itself as selling.
- The shop says payments are accepted while the payout account cannot charge.
- A viewer's ticket count includes someone else's tickets or a refunded order.

Checkout
- An empty or oversized basket still opens Checkout.
- Checkout opens while Stripe is off, or the sphere has no account that charges.
- A ticket type id from another event, an archived one, or one not yet on sale
  is sold.
- More seats are sold than are left, or a sold-out type is sold at all.
- A started order is not held, has the wrong total or fee, or the buyer is not
  sent to Stripe.
- The fee ignores the sphere's deal, or keeps a deal's rate after it lapsed.
- A guest's order is tied to an account, gets a guessable or overlong
  reference, or Stripe sends the guest back to a page keyed by anything else.
- Stripe refusing to open Checkout leaves the seats held by a dead order.

Guest holds
- One guest network holds order after order, so a script sits on a sell-out.
- Orders that no longer hold seats still count against the network, so a
  guest is locked out by checkouts long given up; or a hold whose seats are
  still held through the webhook grace stops counting when the hold lapses.
- The limit reached by one network or on one event locks out another, or
  limits an account at all.
- A guest's order does not record its network, so it never counts.
"""

import logging
from datetime import timedelta

import pytest

from ludamus.pacts.tickets import (
    ORDER_REFERENCE_MAX_LENGTH,
    CheckoutBuyer,
    CheckoutOutcome,
    CheckoutStartDTO,
    CheckoutUrls,
    OrderStatus,
)
from ludamus.specs.tickets import GUEST_HOLDS_PER_CLIENT, WEBHOOK_GRACE
from tests.unit.ticket_fakes import (
    ACCOUNT_ID,
    BUYER_EMAIL,
    BUYER_ID,
    EVENT_ID,
    NOW,
    OTHER_BUYER_ID,
    OTHER_EVENT_ID,
    PRICE,
    TICKETS_LOGGER,
    add_guest_order,
    add_order,
)

pytest_plugins = ("tests.unit.ticket_fixtures",)

# Two tickets at 50 zł: 3.5% of 100 zł.
_TWO_TICKETS = 10_000
_FEE_ON_TWO = 350
_CHECKOUT_URL = "https://checkout.stripe.test/cs_1"
_URLS = CheckoutUrls(
    success=lambda reference: f"/orders/{reference}/",
    cancel=lambda reference: f"/orders/{reference}/cancel/",
)
# 96 random bits as URL-safe base64; a counter or a pk is far shorter.
_UNGUESSABLE_REFERENCE_LENGTH = 16
_DEAL_FEE_BPS = 150
# 1.5% of 100 zł.
_DEAL_FEE_ON_TWO = 150
_CLIENT = "client-a"
_OTHER_CLIENT = "client-b"
_ACCOUNT = CheckoutBuyer(user_id=BUYER_ID, email=BUYER_EMAIL, guest_client="")
_GUEST = CheckoutBuyer(user_id=None, email="", guest_client=_CLIENT)


def _start(sales, book, quantities, *, buyer=_ACCOUNT):
    return sales.start_checkout(
        event=book.event, buyer=buyer, quantities=quantities, urls=_URLS
    )


class TestShop:
    def test_free_event_sells_nothing(self, sales, book, accounts):
        accounts.add()

        shop = sales.shop(event=book.event, viewer_id=BUYER_ID)

        assert not shop.has_tickets
        assert not shop.on_sale

    def test_holder_keeps_their_count_once_every_type_is_off_sale(
        self, sales, book, types, orders
    ):
        retired = types.add(is_archived=True)
        add_order(orders, retired, quantity=1, status=OrderStatus.PAID)
        orders.issue_tickets(
            order=book.orders[1],
            tickets=[{"ticket_type_id": retired.pk, "code": "KEEP"}],
        )

        shop = sales.shop(event=book.event, viewer_id=BUYER_ID)

        assert (shop.has_tickets, shop.viewer_ticket_count) == (False, 1)

    def test_shop_counts_only_the_viewers_valid_tickets(
        self, sales, book, types, orders, accounts
    ):
        accounts.add()
        regular = types.add()
        codes = ["AAAA", "BBBB"]
        add_order(orders, regular, status=OrderStatus.PAID)
        orders.issue_tickets(
            order=book.orders[1],
            tickets=[{"ticket_type_id": regular.pk, "code": code} for code in codes],
        )
        add_order(orders, regular, quantity=1, status=OrderStatus.PAID)
        orders.issue_tickets(
            order=book.orders[2],
            tickets=[{"ticket_type_id": regular.pk, "code": "CCCC"}],
        )
        orders.move(
            pk=2,
            to=OrderStatus.REFUNDED,
            allowed_from=frozenset({OrderStatus.PAID}),
            changes={},
        )
        add_order(orders, regular, quantity=3, buyer_id=OTHER_BUYER_ID)

        shop = sales.shop(event=book.event, viewer_id=BUYER_ID)

        assert shop.on_sale
        assert shop.viewer_ticket_count == len(codes)

    def test_anonymous_viewer_holds_no_tickets(self, sales, book, types, accounts):
        accounts.add()
        types.add()

        assert sales.shop(event=book.event, viewer_id=None).viewer_ticket_count == 0

    @pytest.mark.parametrize(
        ("enabled", "charges_enabled"), ((False, True), (True, False))
    )
    def test_shop_is_closed_while_the_account_cannot_charge(
        self, sales, book, types, accounts, payments, enabled, charges_enabled
    ):
        payments.enabled = enabled
        accounts.add(charges_enabled=charges_enabled)
        types.add()

        shop = sales.shop(event=book.event, viewer_id=None)

        assert shop.has_tickets
        assert not shop.accepting_payments


class TestSalesClosed:
    @pytest.mark.parametrize(
        ("enabled", "account", "charges_enabled"),
        ((False, True, True), (True, False, True), (True, True, False)),
    )
    def test_sales_are_closed_without_an_account_that_charges(
        self, sales, book, types, accounts, payments, enabled, account, charges_enabled
    ):
        payments.enabled = enabled
        if account:
            accounts.add(charges_enabled=charges_enabled)
        regular = types.add()

        assert _start(sales, book, {regular.pk: 1}) == CheckoutStartDTO(
            outcome=CheckoutOutcome.SALES_CLOSED
        )
        assert book.orders == {}


@pytest.mark.usefixtures("_account")
class TestStartCheckout:
    @pytest.fixture(name="_account")
    def account_fixture(self, accounts):
        return accounts.add()

    def test_empty_basket_opens_nothing(self, sales, book, types):
        regular = types.add()

        assert _start(sales, book, {regular.pk: 0}) == CheckoutStartDTO(
            outcome=CheckoutOutcome.NOTHING_SELECTED
        )
        assert book.orders == {}

    def test_more_than_one_order_may_hold_is_refused(self, sales, book, types):
        regular, reduced = types.add(), types.add()

        assert _start(sales, book, {regular.pk: 6, reduced.pk: 5}) == (
            CheckoutStartDTO(outcome=CheckoutOutcome.TOO_MANY)
        )
        assert book.orders == {}

    @pytest.mark.parametrize(
        "foreign", ({"event_id": OTHER_EVENT_ID}, {"is_archived": True})
    )
    def test_type_not_offered_here_is_not_sold(self, sales, book, types, foreign):
        regular = types.add()
        elsewhere = types.add(**foreign)

        assert _start(sales, book, {regular.pk: 1, elsewhere.pk: 1}) == (
            CheckoutStartDTO(outcome=CheckoutOutcome.NOT_ON_SALE)
        )
        assert book.orders == {}

    @pytest.mark.parametrize(
        "window",
        (
            {"sales_start": NOW + timedelta(days=1)},
            {"sales_end": NOW - timedelta(days=1)},
        ),
    )
    def test_type_outside_its_sales_window_is_not_sold(
        self, sales, book, types, window
    ):
        regular = types.add(**window)

        assert _start(sales, book, {regular.pk: 1}) == CheckoutStartDTO(
            outcome=CheckoutOutcome.NOT_ON_SALE
        )

    def test_seats_held_by_another_checkout_are_not_sold_twice(
        self, sales, book, types, orders
    ):
        capped = types.add(quantity=3)
        add_order(orders, capped, quantity=2, buyer_id=OTHER_BUYER_ID)

        assert _start(sales, book, {capped.pk: 2}) == CheckoutStartDTO(
            outcome=CheckoutOutcome.SOLD_OUT
        )
        assert len(book.orders) == 1

    def test_sold_out_type_is_not_sold(self, sales, book, types, orders):
        capped = types.add(quantity=2)
        add_order(orders, capped, status=OrderStatus.PAID, buyer_id=OTHER_BUYER_ID)

        assert _start(sales, book, {capped.pk: 1}) == CheckoutStartDTO(
            outcome=CheckoutOutcome.SOLD_OUT
        )

    def test_started_checkout_holds_the_seats_and_sends_the_buyer_to_stripe(
        self, sales, book, types
    ):
        capped = types.add(price=PRICE, quantity=10)
        free_for_all = types.add(price=PRICE)

        started = _start(sales, book, {capped.pk: 2, free_for_all.pk: 0})

        assert started == CheckoutStartDTO(
            outcome=CheckoutOutcome.STARTED, url=_CHECKOUT_URL
        )
        order = book.orders[1]
        assert order.status is OrderStatus.PENDING
        assert order.total == _TWO_TICKETS
        assert order.platform_fee == _FEE_ON_TWO
        assert order.stripe_account_id == ACCOUNT_ID
        assert order.stripe_checkout_session_id == "cs_1"
        assert order.hold_until > NOW
        shop = sales.shop(event=book.event, viewer_id=BUYER_ID)
        assert [offer.remaining for offer in shop.offers] == [8, None]

    def test_guest_checkout_is_keyed_by_a_secret_reference(
        self, sales, book, types, payments
    ):
        regular = types.add()

        _start(sales, book, {regular.pk: 1}, buyer=_GUEST)
        _start(sales, book, {regular.pk: 1}, buyer=_GUEST)

        first, second = book.orders[1], book.orders[2]
        assert (first.buyer_id, first.email) == (None, "")
        assert first.reference != second.reference
        assert (
            _UNGUESSABLE_REFERENCE_LENGTH
            <= len(first.reference)
            <= ORDER_REFERENCE_MAX_LENGTH
        )
        request = payments.checkouts[0]
        assert (request.customer_email, request.success_url, request.cancel_url) == (
            "",
            f"/orders/{first.reference}/",
            f"/orders/{first.reference}/cancel/",
        )

    @pytest.mark.parametrize(
        ("paid_until", "fee"),
        ((None, _DEAL_FEE_ON_TWO), (NOW, _FEE_ON_TWO)),
        ids=("deal", "lapsed-deal"),
    )
    def test_fee_is_the_spheres_rate_today(
        self, sales, book, types, plans, payments, paid_until, fee
    ):
        plans.add(ticket_fee_bps=_DEAL_FEE_BPS, paid_until=paid_until)
        regular = types.add(price=PRICE)

        _start(sales, book, {regular.pk: 2})

        assert book.orders[1].platform_fee == fee
        assert payments.checkouts[0].application_fee == fee

    def test_stripe_refusing_checkout_releases_the_seats(
        self, sales, book, types, payments
    ):
        capped = types.add(quantity=2)
        payments.down.add("create_checkout")

        started = _start(sales, book, {capped.pk: 2})

        assert started == CheckoutStartDTO(outcome=CheckoutOutcome.PROVIDER_ERROR)
        assert book.orders[1].status is OrderStatus.FAILED
        shop = sales.shop(event=book.event, viewer_id=BUYER_ID)
        assert shop.offers[0].remaining == capped.quantity


@pytest.mark.usefixtures("_account")
class TestGuestHoldLimit:
    @pytest.fixture(name="_account")
    def account_fixture(self, accounts):
        return accounts.add()

    @pytest.fixture(name="regular")
    def regular_fixture(self, types):
        return types.add()

    @staticmethod
    def _hold(orders, ticket_type, *, holds=GUEST_HOLDS_PER_CLIENT, **overrides):
        for _ in range(holds):
            add_guest_order(
                orders, ticket_type, **({"guest_client": _CLIENT} | overrides)
            )

    def test_guest_under_the_limit_starts_and_the_order_counts_for_the_network(
        self, sales, book, orders, regular
    ):
        self._hold(orders, regular, holds=GUEST_HOLDS_PER_CLIENT - 1)

        started = _start(sales, book, {regular.pk: 1}, buyer=_GUEST)
        refused = _start(sales, book, {regular.pk: 1}, buyer=_GUEST)

        assert (started.outcome, refused.outcome) == (
            CheckoutOutcome.STARTED,
            CheckoutOutcome.TOO_MANY_HOLDS,
        )
        assert book.guest_clients == dict.fromkeys(book.orders, _CLIENT)

    def test_guest_at_the_limit_is_refused_and_it_is_logged(
        self, sales, book, orders, regular, payments, caplog
    ):
        self._hold(orders, regular)
        before = dict(book.orders)

        with caplog.at_level(logging.WARNING, logger=TICKETS_LOGGER):
            started = _start(sales, book, {regular.pk: 1}, buyer=_GUEST)

        assert started == CheckoutStartDTO(outcome=CheckoutOutcome.TOO_MANY_HOLDS)
        assert book.orders == before
        assert payments.checkouts == []
        assert caplog.messages == [f"Guest holds at the limit: event={EVENT_ID}"]

    @pytest.mark.parametrize(
        "holding",
        (
            pytest.param({"status": OrderStatus.AWAITING_PAYMENT}, id="bank-transfer"),
            pytest.param(
                {"hold_until": NOW - WEBHOOK_GRACE + timedelta(minutes=30)},
                id="hold-lapsed-within-the-grace",
            ),
        ),
    )
    def test_orders_still_holding_seats_count_as_holds(
        self, sales, book, orders, regular, holding
    ):
        self._hold(orders, regular, **holding)

        started = _start(sales, book, {regular.pk: 1}, buyer=_GUEST)

        assert started.outcome is CheckoutOutcome.TOO_MANY_HOLDS

    @pytest.mark.parametrize(
        "done",
        (
            pytest.param(
                {"hold_until": NOW - WEBHOOK_GRACE - timedelta(minutes=30)},
                id="hold-lapsed-past-the-grace",
            ),
            pytest.param({"status": OrderStatus.EXPIRED}, id="expired"),
            pytest.param({"status": OrderStatus.FAILED}, id="failed"),
            pytest.param({"status": OrderStatus.PAID}, id="paid"),
            pytest.param({"buyer_id": OTHER_BUYER_ID}, id="claimed"),
        ),
    )
    def test_orders_that_hold_nothing_more_leave_the_network_free(
        self, sales, book, orders, regular, done
    ):
        self._hold(orders, regular, **done)

        started = _start(sales, book, {regular.pk: 1}, buyer=_GUEST)

        assert started.outcome is CheckoutOutcome.STARTED

    @pytest.mark.parametrize(
        "buyer",
        (
            pytest.param(
                CheckoutBuyer(user_id=None, email="", guest_client=_OTHER_CLIENT),
                id="another-network",
            ),
            pytest.param(
                CheckoutBuyer(
                    user_id=BUYER_ID, email=BUYER_EMAIL, guest_client=_CLIENT
                ),
                id="account-on-the-network",
            ),
        ),
    )
    def test_limit_of_one_network_leaves_the_others_and_accounts_be(
        self, sales, book, orders, regular, buyer
    ):
        self._hold(orders, regular)

        started = _start(sales, book, {regular.pk: 1}, buyer=buyer)

        assert started.outcome is CheckoutOutcome.STARTED

    def test_limit_on_another_event_leaves_this_one_be(
        self, sales, book, orders, types, regular
    ):
        self._hold(orders, types.add(event_id=OTHER_EVENT_ID), event_id=OTHER_EVENT_ID)

        started = _start(sales, book, {regular.pk: 1}, buyer=_GUEST)

        assert started.outcome is CheckoutOutcome.STARTED
