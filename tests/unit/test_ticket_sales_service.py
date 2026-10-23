"""Ticket sales: the payout account, the shop, checkout, the webhook, the panel.

Ways these services could fail, each pinned below:

Payout account
- Connecting twice opens a second Stripe account instead of resuming the first.
- Resuming onboarding for a sphere that never connected sends it somewhere.
- Coming back from onboarding shows the stale state Stripe has since changed.

Shop and checkout
- A free event (no ticket types) reports itself as selling.
- The shop says payments are accepted while the payout account cannot charge.
- A viewer's ticket count includes someone else's tickets or a refunded order.
- An empty or oversized basket still opens Checkout.
- Checkout opens while Stripe is off, or the sphere has no account that charges.
- A ticket type id from another event, an archived one, or one not yet on sale
  is sold.
- More seats are sold than are left, or a sold-out type is sold at all.
- A started order is not held, has the wrong total or fee, or the buyer is not
  sent to Stripe.
- Stripe refusing to open Checkout leaves the seats held by a dead order.

Buyer's order
- Another buyer's order, or one from another event, is shown.
- The page polls for an order Stripe will not settle within seconds.
- Abandoning Checkout expires an order Stripe already completed, or expires an
  order that is no longer pending.

Webhook
- A redelivered or reordered event moves an order backwards or twice.
- An event for someone else's session, account or payment intent touches ours.
- A partial refund voids the tickets.
- A delayed payment issues tickets before it settles.
- Money taken for an order we gave up on is kept, or tickets are issued for it.
- A late payment that cannot be refunded is reported as refunded.
- Seats resold while a payment was late go unnoticed.

Panel
- Archived types are priced as if on sale, or vanish from the panel.
- The takings count unpaid or refunded orders.
- The order list hides that older orders were left out.
- A ticket type or order of another event is read, changed or refunded.
- An unpaid order is refunded, or Stripe refusing a refund records one anyway.
"""

import logging
from datetime import timedelta
from decimal import Decimal

import pytest

from ludamus.mills.tickets import PayoutService, TicketPanelService, TicketSalesService
from ludamus.pacts.legacy import NotFoundError
from ludamus.pacts.payment_api import (
    AccountEvent,
    AccountState,
    CheckoutEvent,
    CheckoutStage,
    PaymentProviderError,
    RefundEvent,
    SubscriptionEvent,
    UnhandledEvent,
    WebhookOutcome,
)
from ludamus.pacts.tickets import (
    TICKET_CODE_LENGTH,
    CheckoutOutcome,
    CheckoutStartDTO,
    CheckoutUrls,
    OrderStatus,
    PayoutPageDTO,
    PayoutStatus,
    RefundOutcome,
    TicketRepos,
    TicketSalesSummaryDTO,
)
from ludamus.specs.tickets import PANEL_ORDERS_SHOWN
from tests.unit.factories import FakeTransaction
from tests.unit.ticket_fakes import (
    ACCOUNT_ID,
    BUYER_ID,
    EVENT_ID,
    NOW,
    OTHER_BUYER_ID,
    OTHER_EVENT_ID,
    SPHERE_ID,
    FakeAccounts,
    FakeOrders,
    FakePlans,
    FakeTicketPayments,
    FakeTicketTypes,
    TicketBook,
)

_PRICE = 5000
# Two tickets at 50 zł: 3.5% of 100 zł, and Stripe's 2.9% + 0.30 zł estimate.
_TWO_TICKETS = 10_000
_FEE_ON_TWO = 350
_STRIPE_FEE_ON_TWO = 320
_FEE_PERCENT = Decimal("3.5")
_CHECKOUT_URL = "https://checkout.stripe.test/cs_1"
_CODE_ALPHABET = set("ABCDEFGHJKMNPQRSTUVWXYZ23456789")
_URLS = CheckoutUrls(
    success=lambda pk: f"/orders/{pk}/", cancel=lambda pk: f"/orders/{pk}/cancel/"
)
_TICKETS_LOGGER = "ludamus.mills.tickets"


@pytest.fixture(name="book")
def book_fixture():
    return TicketBook()


@pytest.fixture(name="types")
def types_fixture(book):
    return FakeTicketTypes(book)


@pytest.fixture(name="orders")
def orders_fixture(book):
    return FakeOrders(book)


@pytest.fixture(name="accounts")
def accounts_fixture():
    return FakeAccounts()


@pytest.fixture(name="payments")
def payments_fixture():
    return FakeTicketPayments()


@pytest.fixture(name="repos")
def repos_fixture(types, orders, accounts):
    return TicketRepos(
        ticket_types=types, orders=orders, accounts=accounts, plans=FakePlans()
    )


@pytest.fixture(name="payout")
def payout_fixture(accounts, payments):
    return PayoutService(
        transaction=FakeTransaction(), accounts=accounts, payments=payments
    )


@pytest.fixture(name="sales")
def sales_fixture(repos, payments):
    return TicketSalesService(
        transaction=FakeTransaction(), repos=repos, payments=payments
    )


@pytest.fixture(name="panel")
def panel_fixture(repos, payments):
    return TicketPanelService(
        transaction=FakeTransaction(), repos=repos, payments=payments
    )


def _order(orders, ticket_type, *, quantity=2, **overrides):
    return orders.add(
        lines=[
            {
                "ticket_type_id": ticket_type.pk,
                "quantity": quantity,
                "unit_price": ticket_type.price,
            }
        ],
        **overrides,
    )


def _checkout(stage, *, session_id="cs_1", paid=True):
    return CheckoutEvent(
        stage=stage, session_id=session_id, paid=paid, payment_intent_id="pi_1"
    )


def _deliver(sales, payments, event):
    payments.event = event
    return sales.handle_webhook(payload=b"{}", signature="sig")


def _start(sales, book, quantities):
    return sales.start_checkout(
        event=book.event,
        buyer_id=BUYER_ID,
        email="buyer@example.com",
        quantities=quantities,
        urls=_URLS,
    )


def _status(book, order):
    return book.orders[order.pk].status


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


class TestShop:
    def test_free_event_sells_nothing(self, sales, book, accounts):
        accounts.add()

        shop = sales.shop(event=book.event, viewer_id=BUYER_ID)

        assert not shop.has_tickets
        assert not shop.on_sale

    def test_shop_counts_only_the_viewers_valid_tickets(
        self, sales, book, types, orders, accounts
    ):
        accounts.add()
        regular = types.add()
        codes = ["AAAA", "BBBB"]
        _order(orders, regular, status=OrderStatus.PAID)
        orders.issue_tickets(order=book.orders[1], codes=codes)
        _order(orders, regular, quantity=1, status=OrderStatus.PAID)
        orders.issue_tickets(order=book.orders[2], codes=["CCCC"])
        orders.void_tickets(order_pk=2)
        _order(orders, regular, quantity=3, buyer_id=OTHER_BUYER_ID)

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
        _order(orders, capped, quantity=2, buyer_id=OTHER_BUYER_ID)

        assert _start(sales, book, {capped.pk: 2}) == CheckoutStartDTO(
            outcome=CheckoutOutcome.SOLD_OUT
        )
        assert len(book.orders) == 1

    def test_sold_out_type_is_not_sold(self, sales, book, types, orders):
        capped = types.add(quantity=2)
        _order(orders, capped, status=OrderStatus.PAID, buyer_id=OTHER_BUYER_ID)

        assert _start(sales, book, {capped.pk: 1}) == CheckoutStartDTO(
            outcome=CheckoutOutcome.SOLD_OUT
        )

    def test_started_checkout_holds_the_seats_and_sends_the_buyer_to_stripe(
        self, sales, book, types
    ):
        capped = types.add(price=_PRICE, quantity=10)
        free_for_all = types.add(price=_PRICE)

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


class TestBuyerOrder:
    @pytest.mark.parametrize(
        ("buyer_id", "event_id"),
        ((OTHER_BUYER_ID, EVENT_ID), (BUYER_ID, OTHER_EVENT_ID)),
    )
    def test_someone_elses_order_is_not_found(
        self, sales, book, types, orders, buyer_id, event_id
    ):
        order = _order(orders, types.add())

        with pytest.raises(NotFoundError):
            sales.order(buyer_id=buyer_id, event_id=event_id, pk=order.pk)
        with pytest.raises(NotFoundError):
            sales.abandon_checkout(buyer_id=buyer_id, event_id=event_id, pk=order.pk)
        assert book.orders[order.pk] == order

    @pytest.mark.parametrize(
        ("status", "hold", "confirming", "polling"),
        (
            (OrderStatus.PENDING, timedelta(minutes=30), True, True),
            (OrderStatus.PENDING, -timedelta(minutes=1), True, False),
            (OrderStatus.AWAITING_PAYMENT, timedelta(minutes=30), True, False),
            (OrderStatus.PAID, timedelta(minutes=30), False, False),
        ),
    )
    def test_order_page_polls_only_while_stripe_will_answer_soon(
        self, sales, types, orders, status, hold, confirming, polling
    ):
        order = _order(orders, types.add(), status=status, hold_until=NOW + hold)

        page = sales.order(buyer_id=BUYER_ID, event_id=EVENT_ID, pk=order.pk)

        assert (page.confirming, page.polling) == (confirming, polling)

    @pytest.mark.parametrize("session_id", ("cs_1", ""))
    def test_abandoning_checkout_expires_the_pending_order(
        self, sales, book, types, orders, session_id
    ):
        order = _order(orders, types.add(), stripe_checkout_session_id=session_id)

        sales.abandon_checkout(buyer_id=BUYER_ID, event_id=EVENT_ID, pk=order.pk)

        assert _status(book, order) is OrderStatus.EXPIRED

    def test_abandoning_a_checkout_stripe_already_closed_leaves_it_to_the_webhook(
        self, sales, book, types, orders, payments
    ):
        order = _order(orders, types.add(), stripe_checkout_session_id="cs_1")
        payments.down.add("expire_checkout")

        sales.abandon_checkout(buyer_id=BUYER_ID, event_id=EVENT_ID, pk=order.pk)

        assert _status(book, order) is OrderStatus.PENDING

    def test_abandoning_a_paid_order_changes_nothing(self, sales, book, types, orders):
        order = _order(orders, types.add(), status=OrderStatus.PAID)

        sales.abandon_checkout(buyer_id=BUYER_ID, event_id=EVENT_ID, pk=order.pk)

        assert _status(book, order) is OrderStatus.PAID


class TestWebhook:
    def test_known_account_update_is_stored(self, sales, accounts, payments):
        accounts.add(charges_enabled=False)
        state = AccountState(
            details_submitted=True, charges_enabled=True, payouts_enabled=False
        )

        outcome = _deliver(
            sales, payments, AccountEvent(account_id=ACCOUNT_ID, state=state)
        )

        assert outcome is WebhookOutcome.ACCOUNT_UPDATED
        assert accounts.rows[SPHERE_ID].charges_enabled

    def test_unknown_account_update_is_not_ours(self, sales, accounts, payments):
        accounts.add(charges_enabled=False)
        state = AccountState(
            details_submitted=True, charges_enabled=True, payouts_enabled=True
        )

        outcome = _deliver(
            sales, payments, AccountEvent(account_id="acct_other", state=state)
        )

        assert outcome is WebhookOutcome.NOT_OURS
        assert not accounts.rows[SPHERE_ID].charges_enabled

    @pytest.mark.parametrize(
        "event",
        (
            SubscriptionEvent(subscription_id="sub_1"),
            UnhandledEvent(type="customer.created"),
            _checkout(CheckoutStage.COMPLETED, session_id="cs_other"),
            RefundEvent(payment_intent_id="pi_other", fully_refunded=True),
        ),
    )
    def test_event_about_nothing_of_ours_changes_nothing(
        self, sales, book, types, orders, payments, event
    ):
        order = _order(orders, types.add(), stripe_checkout_session_id="cs_1")

        assert _deliver(sales, payments, event) is WebhookOutcome.NOT_OURS
        assert book.orders[order.pk] == order

    def test_paid_checkout_issues_one_code_per_seat(
        self, sales, book, types, orders, payments
    ):
        order = _order(orders, types.add(), stripe_checkout_session_id="cs_1")

        outcome = _deliver(sales, payments, _checkout(CheckoutStage.COMPLETED))

        assert outcome is WebhookOutcome.PAID
        paid = book.orders[order.pk]
        assert paid.status is OrderStatus.PAID
        assert paid.stripe_payment_intent_id == "pi_1"
        assert paid.paid_at is not None
        codes = [ticket.code for ticket in paid.tickets]
        assert len(codes) == order.ticket_count
        assert all(len(code) == TICKET_CODE_LENGTH for code in codes)
        assert set("".join(codes)) <= _CODE_ALPHABET

    def test_redelivered_payment_issues_nothing_more(
        self, sales, book, types, orders, payments
    ):
        order = _order(orders, types.add(), stripe_checkout_session_id="cs_1")
        _deliver(sales, payments, _checkout(CheckoutStage.COMPLETED))
        issued = book.orders[order.pk]

        outcome = _deliver(sales, payments, _checkout(CheckoutStage.ASYNC_SUCCEEDED))

        assert outcome is WebhookOutcome.STALE
        assert book.orders[order.pk] == issued
        assert payments.refunded == []

    def test_delayed_payment_holds_seats_until_it_settles(
        self, sales, book, types, orders, payments
    ):
        order = _order(orders, types.add(), stripe_checkout_session_id="cs_1")

        completed = _deliver(
            sales, payments, _checkout(CheckoutStage.COMPLETED, paid=False)
        )
        awaiting = book.orders[order.pk]
        settled = _deliver(sales, payments, _checkout(CheckoutStage.ASYNC_SUCCEEDED))

        assert completed is WebhookOutcome.AWAITING_PAYMENT
        assert awaiting.status is OrderStatus.AWAITING_PAYMENT
        assert awaiting.stripe_payment_intent_id == "pi_1"
        assert awaiting.tickets == []
        assert settled is WebhookOutcome.PAID
        assert len(book.orders[order.pk].tickets) == order.ticket_count

    def test_failed_delayed_payment_is_final(
        self, sales, book, types, orders, payments
    ):
        order = _order(
            orders,
            types.add(),
            stripe_checkout_session_id="cs_1",
            status=OrderStatus.AWAITING_PAYMENT,
        )

        failed = _deliver(sales, payments, _checkout(CheckoutStage.ASYNC_FAILED))
        late_completion = _deliver(
            sales, payments, _checkout(CheckoutStage.COMPLETED, paid=False)
        )

        assert (failed, late_completion) == (
            WebhookOutcome.FAILED,
            WebhookOutcome.STALE,
        )
        assert _status(book, order) is OrderStatus.FAILED

    def test_expired_checkout_releases_the_order_once(
        self, sales, book, types, orders, payments
    ):
        order = _order(orders, types.add(), stripe_checkout_session_id="cs_1")

        first = _deliver(sales, payments, _checkout(CheckoutStage.EXPIRED))
        again = _deliver(sales, payments, _checkout(CheckoutStage.EXPIRED))

        assert (first, again) == (WebhookOutcome.EXPIRED, WebhookOutcome.STALE)
        assert _status(book, order) is OrderStatus.EXPIRED

    @pytest.mark.parametrize("given_up", (OrderStatus.EXPIRED, OrderStatus.FAILED))
    def test_payment_for_an_order_given_up_on_is_refunded(
        self, sales, book, types, orders, payments, given_up
    ):
        order = _order(
            orders, types.add(), stripe_checkout_session_id="cs_1", status=given_up
        )

        outcome = _deliver(sales, payments, _checkout(CheckoutStage.COMPLETED))

        assert outcome is WebhookOutcome.REFUNDED
        assert payments.refunded == ["pi_1"]
        assert book.orders[order.pk] == order

    def test_late_payment_stripe_will_not_refund_fails_the_delivery(
        self, sales, book, types, orders, payments
    ):
        order = _order(
            orders,
            types.add(),
            stripe_checkout_session_id="cs_1",
            status=OrderStatus.EXPIRED,
        )
        payments.down.add("refund_once")

        with pytest.raises(PaymentProviderError):
            _deliver(sales, payments, _checkout(CheckoutStage.COMPLETED))

        assert payments.refunded == []
        assert book.orders[order.pk] == order

    def test_payment_after_the_seats_were_resold_is_flagged_as_oversold(
        self, sales, book, types, orders, payments, caplog
    ):
        capped = types.add(quantity=2)
        uncapped = types.add()
        _order(
            orders,
            capped,
            stripe_checkout_session_id="cs_late",
            hold_until=NOW - timedelta(hours=2),
        )
        _order(orders, capped, status=OrderStatus.PAID, buyer_id=OTHER_BUYER_ID)
        _order(orders, uncapped, status=OrderStatus.PAID, buyer_id=OTHER_BUYER_ID)

        with caplog.at_level(logging.WARNING, logger=_TICKETS_LOGGER):
            outcome = _deliver(
                sales,
                payments,
                _checkout(CheckoutStage.COMPLETED, session_id="cs_late"),
            )

        assert outcome is WebhookOutcome.PAID
        assert caplog.messages == [
            f"Ticket type oversold: event={EVENT_ID} type={capped.pk} sold=4 cap=2"
        ]

    def test_full_refund_voids_the_tickets_once(
        self, sales, book, types, orders, payments
    ):
        order = _order(orders, types.add(), stripe_checkout_session_id="cs_1")
        _deliver(sales, payments, _checkout(CheckoutStage.COMPLETED))
        refund = RefundEvent(payment_intent_id="pi_1", fully_refunded=True)

        first = _deliver(sales, payments, refund)
        refunded = book.orders[order.pk]
        again = _deliver(sales, payments, refund)

        assert (first, again) == (WebhookOutcome.REFUNDED, WebhookOutcome.STALE)
        assert refunded.status is OrderStatus.REFUNDED
        assert refunded.refunded_at is not None
        assert all(ticket.is_void for ticket in refunded.tickets)
        assert book.orders[order.pk] == refunded
        assert sales.owned_tickets(sphere_id=SPHERE_ID, holder_id=BUYER_ID) == []

    def test_partial_refund_keeps_the_tickets(
        self, sales, book, types, orders, payments
    ):
        order = _order(orders, types.add(), stripe_checkout_session_id="cs_1")
        _deliver(sales, payments, _checkout(CheckoutStage.COMPLETED))
        paid = book.orders[order.pk]

        outcome = _deliver(
            sales, payments, RefundEvent(payment_intent_id="pi_1", fully_refunded=False)
        )

        assert outcome is WebhookOutcome.NOT_OURS
        assert book.orders[order.pk] == paid
        owned = sales.owned_tickets(sphere_id=SPHERE_ID, holder_id=BUYER_ID)
        assert [ticket.code for ticket in owned] == [
            ticket.code for ticket in paid.tickets
        ]


class TestPanel:
    def test_page_prices_live_types_and_totals_only_paid_orders(
        self, panel, types, orders, accounts
    ):
        accounts.add(charges_enabled=False)
        on_sale = types.add(price=_PRICE)
        retired = types.add(is_archived=True)
        types.add(event_id=OTHER_EVENT_ID)
        paid = _order(
            orders, on_sale, status=OrderStatus.PAID, platform_fee=_FEE_ON_TWO
        )
        refunded = _order(orders, on_sale, status=OrderStatus.REFUNDED)
        _order(orders, on_sale, status=OrderStatus.EXPIRED)
        _order(orders, on_sale, status=OrderStatus.PAID, event_id=OTHER_EVENT_ID)

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

    def test_page_says_when_older_orders_were_left_out(self, panel, types, orders):
        regular = types.add()
        for _ in range(PANEL_ORDERS_SHOWN + 1):
            _order(orders, regular, status=OrderStatus.PAID)

        page = panel.page(sphere_id=SPHERE_ID, event_id=EVENT_ID)

        assert len(page.orders) == PANEL_ORDERS_SHOWN
        assert page.orders[0].pk == PANEL_ORDERS_SHOWN + 1
        assert page.more_orders

    def test_type_of_another_event_is_not_found(self, panel, book, types):
        foreign = types.add(event_id=OTHER_EVENT_ID)
        data = {
            "name": "Renamed",
            "description": "",
            "price": _PRICE,
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
            "price": _PRICE,
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
        foreign = _order(
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
        order = _order(
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
        order = _order(
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
        order = _order(orders, types.add(), stripe_checkout_session_id="cs_1")
        _deliver(sales, payments, _checkout(CheckoutStage.COMPLETED))

        outcome = panel.refund(event_id=EVENT_ID, order_pk=order.pk)
        webhook = _deliver(
            sales, payments, RefundEvent(payment_intent_id="pi_1", fully_refunded=True)
        )

        assert outcome is RefundOutcome.REFUNDED
        assert webhook is WebhookOutcome.STALE
        assert payments.refunded == ["pi_1"]
        refunded = book.orders[order.pk]
        assert refunded.status is OrderStatus.REFUNDED
        assert all(ticket.is_void for ticket in refunded.tickets)
