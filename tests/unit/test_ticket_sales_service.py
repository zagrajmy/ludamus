"""Ticket sales: the payout account, the shop, checkout, the webhook, the panel.

Ways these services could fail, each pinned below:

Payout account
- Connecting twice opens a second Stripe account instead of resuming the first.
- Resuming onboarding for a sphere that never connected sends it somewhere.
- Coming back from onboarding shows the stale state Stripe has since changed.

Shop and checkout
- A guest from one address holds checkout after checkout, or the limit for one
  address or event locks out another.
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
- The fee ignores the sphere's deal, or keeps a deal's rate after it lapsed.
- A guest's order is tied to an account, gets a guessable or overlong
  reference, or Stripe sends the guest back to a page keyed by anything else.
- Stripe refusing to open Checkout leaves the seats held by a dead order.

Buyer's order
- An order claimed into an account is shown to anyone else, an order from
  another event is shown, or a guest's order is hidden from its link.
- The page polls for an order Stripe will not settle within seconds.
- Abandoning Checkout expires an order Stripe already completed, expires an
  order that is no longer pending, or expires someone else's.
- Claiming takes an order another account holds, or leaves its tickets out of
  the new holder's count.

Webhook
- A redelivered or reordered event moves an order backwards or twice.
- An event for someone else's session, account or payment intent touches ours.
- A partial refund voids the tickets.
- A delayed payment issues tickets before it settles.
- Money taken for an order we gave up on is kept, or tickets are issued for it.
- A late payment that cannot be refunded is reported as refunded.
- Seats resold while a payment was late go unnoticed.
- A guest's email from Checkout is not kept on the order.
- The order mail is not sent when Checkout completes, is sent again on a
  redelivery or when the money settles, or is sent for a refunded late payment.
- An order with no email anywhere crashes the webhook instead of skipping mail.

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
    ORDER_REFERENCE_MAX_LENGTH,
    TICKET_CODE_LENGTH,
    AbandonOutcome,
    CheckoutOutcome,
    CheckoutStartDTO,
    CheckoutUrls,
    ClaimOutcome,
    OrderLinkMail,
    OrderPageState,
    OrderStatus,
    PayoutPageDTO,
    PayoutStatus,
    RefundOutcome,
    TicketRepos,
    TicketSalesSummaryDTO,
)
from ludamus.specs.tickets import (
    GUEST_CHECKOUT_WINDOW_SECONDS,
    GUEST_CHECKOUTS_PER_WINDOW,
    PANEL_ORDERS_SHOWN,
)
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
    FakeCache,
    FakeMailer,
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
    success=lambda reference: f"/orders/{reference}/",
    cancel=lambda reference: f"/orders/{reference}/cancel/",
)
_TICKETS_LOGGER = "ludamus.mills.tickets"
_GUEST_EMAIL = "guest@example.com"
# 96 random bits as URL-safe base64; a counter or a pk is far shorter.
_UNGUESSABLE_REFERENCE_LENGTH = 16
_DEAL_FEE_BPS = 150
# 1.5% of 100 zł.
_DEAL_FEE_ON_TWO = 150


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


@pytest.fixture(name="plans")
def plans_fixture():
    return FakePlans()


@pytest.fixture(name="mailer")
def mailer_fixture():
    return FakeMailer()


@pytest.fixture(name="cache")
def cache_fixture():
    return FakeCache()


@pytest.fixture(name="repos")
def repos_fixture(types, orders, accounts, plans):
    return TicketRepos(
        ticket_types=types, orders=orders, accounts=accounts, plans=plans
    )


@pytest.fixture(name="payout")
def payout_fixture(accounts, payments):
    return PayoutService(
        transaction=FakeTransaction(), accounts=accounts, payments=payments
    )


@pytest.fixture(name="sales")
def sales_fixture(repos, payments, mailer, cache):
    return TicketSalesService(
        transaction=FakeTransaction(),
        repos=repos,
        payments=payments,
        mailer=mailer,
        cache=cache,
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


def _checkout(stage, *, session_id="cs_1", paid=True, email=""):
    return CheckoutEvent(
        stage=stage,
        session_id=session_id,
        paid=paid,
        payment_intent_id="pi_1",
        email=email,
    )


def _deliver(sales, payments, event):
    payments.event = event
    return sales.handle_webhook(payload=b"{}", signature="sig")


def _start(sales, book, quantities, *, buyer_id=BUYER_ID, email="buyer@example.com"):
    return sales.start_checkout(
        event=book.event,
        buyer_id=buyer_id,
        email=email,
        quantities=quantities,
        urls=_URLS,
    )


def _guest_order(orders, ticket_type, **overrides):
    return _order(orders, ticket_type, buyer_id=None, email="", **overrides)


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

    def test_holder_keeps_their_count_once_every_type_is_off_sale(
        self, sales, book, types, orders
    ):
        retired = types.add(is_archived=True)
        _order(orders, retired, quantity=1, status=OrderStatus.PAID)
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
        _order(orders, regular, status=OrderStatus.PAID)
        orders.issue_tickets(
            order=book.orders[1],
            tickets=[{"ticket_type_id": regular.pk, "code": code} for code in codes],
        )
        _order(orders, regular, quantity=1, status=OrderStatus.PAID)
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


class TestGuestCheckoutLimit:
    def test_one_address_is_refused_past_the_limit_for_the_window(self, sales, cache):
        allowed = [
            sales.guest_checkout_allowed(ip="203.0.113.1", event_id=EVENT_ID)
            for _ in range(GUEST_CHECKOUTS_PER_WINDOW + 1)
        ]

        assert allowed == [True] * GUEST_CHECKOUTS_PER_WINDOW + [False]
        assert set(cache.timeouts.values()) == {GUEST_CHECKOUT_WINDOW_SECONDS}

    def test_limit_reached_at_one_address_and_event_leaves_the_others(self, sales):
        for _ in range(GUEST_CHECKOUTS_PER_WINDOW):
            sales.guest_checkout_allowed(ip="203.0.113.1", event_id=EVENT_ID)

        assert sales.guest_checkout_allowed(ip="203.0.113.2", event_id=EVENT_ID)
        assert sales.guest_checkout_allowed(ip="203.0.113.1", event_id=OTHER_EVENT_ID)

    def test_refusal_is_logged(self, sales, caplog):
        for _ in range(GUEST_CHECKOUTS_PER_WINDOW):
            sales.guest_checkout_allowed(ip="203.0.113.1", event_id=EVENT_ID)

        with caplog.at_level(logging.WARNING, logger=_TICKETS_LOGGER):
            sales.guest_checkout_allowed(ip="203.0.113.1", event_id=EVENT_ID)

        assert caplog.messages == [f"Guest checkouts over the limit: event={EVENT_ID}"]


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

    def test_guest_checkout_is_keyed_by_a_secret_reference(
        self, sales, book, types, payments
    ):
        regular = types.add()

        _start(sales, book, {regular.pk: 1}, buyer_id=None, email="")
        _start(sales, book, {regular.pk: 1}, buyer_id=None, email="")

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
        regular = types.add(price=_PRICE)

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


class TestBuyerOrder:
    @pytest.mark.parametrize(
        ("event_id", "reference", "viewer_id"),
        (
            pytest.param(EVENT_ID, "ref1", OTHER_BUYER_ID, id="someone-elses"),
            pytest.param(EVENT_ID, "ref1", None, id="claimed-and-signed-out"),
            pytest.param(OTHER_EVENT_ID, "ref1", BUYER_ID, id="another-event"),
            pytest.param(EVENT_ID, "nope", BUYER_ID, id="unknown-reference"),
        ),
    )
    def test_order_out_of_the_viewers_reach_is_not_found(
        self, sales, book, types, orders, payments, event_id, reference, viewer_id
    ):
        order = _order(orders, types.add(), stripe_checkout_session_id="cs_1")
        payments.down.add("expire_checkout")

        with pytest.raises(NotFoundError):
            sales.order(event_id=event_id, reference=reference, viewer_id=viewer_id)
        with pytest.raises(NotFoundError):
            sales.abandon_checkout(
                event_id=event_id, reference=reference, viewer_id=viewer_id
            )
        assert book.orders[order.pk] == order

    def test_guest_order_is_its_links_whoever_holds_it(self, sales, types, orders):
        order = _guest_order(orders, types.add())

        pages = [
            sales.order(event_id=EVENT_ID, reference=order.reference, viewer_id=viewer)
            for viewer in (None, OTHER_BUYER_ID)
        ]

        assert [(page.order, page.claimable) for page in pages] == [
            (order, True),
            (order, True),
        ]

    def test_order_held_by_an_account_is_not_offered_to_claim(
        self, sales, types, orders
    ):
        order = _order(orders, types.add())

        page = sales.order(
            event_id=EVENT_ID, reference=order.reference, viewer_id=BUYER_ID
        )

        assert not page.claimable

    @pytest.mark.parametrize(
        ("status", "hold", "state"),
        (
            (OrderStatus.PENDING, timedelta(minutes=30), OrderPageState.CONFIRMING),
            (
                OrderStatus.PENDING,
                -timedelta(minutes=1),
                OrderPageState.CONFIRMATION_LATE,
            ),
            (
                OrderStatus.AWAITING_PAYMENT,
                timedelta(minutes=30),
                OrderPageState.AWAITING_TRANSFER,
            ),
            (OrderStatus.PAID, timedelta(minutes=30), OrderPageState.PAID),
            (OrderStatus.REFUNDED, timedelta(minutes=30), OrderPageState.REFUNDED),
            (OrderStatus.EXPIRED, timedelta(minutes=30), OrderPageState.NOT_COMPLETED),
            (OrderStatus.FAILED, timedelta(minutes=30), OrderPageState.NOT_COMPLETED),
        ),
    )
    def test_order_page_says_where_the_order_stands(
        self, sales, types, orders, status, hold, state
    ):
        order = _order(orders, types.add(), status=status, hold_until=NOW + hold)

        page = sales.order(
            event_id=EVENT_ID, reference=order.reference, viewer_id=BUYER_ID
        )

        assert page.state is state

    @pytest.mark.parametrize("session_id", ("cs_1", ""))
    @pytest.mark.parametrize(
        ("buyer_id", "viewer_id"),
        ((BUYER_ID, BUYER_ID), (None, None)),
        ids=("holder", "guest"),
    )
    def test_abandoning_checkout_expires_the_pending_order(
        self, sales, book, types, orders, session_id, buyer_id, viewer_id
    ):
        order = _order(
            orders,
            types.add(),
            buyer_id=buyer_id,
            stripe_checkout_session_id=session_id,
        )

        outcome = sales.abandon_checkout(
            event_id=EVENT_ID, reference=order.reference, viewer_id=viewer_id
        )

        assert outcome is AbandonOutcome.CANCELLED
        assert _status(book, order) is OrderStatus.EXPIRED

    def test_abandoning_a_checkout_stripe_already_closed_leaves_it_to_the_webhook(
        self, sales, book, types, orders, payments
    ):
        order = _order(orders, types.add(), stripe_checkout_session_id="cs_1")
        payments.down.add("expire_checkout")

        outcome = sales.abandon_checkout(
            event_id=EVENT_ID, reference=order.reference, viewer_id=BUYER_ID
        )

        assert outcome is AbandonOutcome.UNCONFIRMED
        assert _status(book, order) is OrderStatus.PENDING

    def test_abandoning_a_paid_order_changes_nothing(self, sales, book, types, orders):
        order = _order(orders, types.add(), status=OrderStatus.PAID)

        outcome = sales.abandon_checkout(
            event_id=EVENT_ID, reference=order.reference, viewer_id=BUYER_ID
        )

        assert outcome is AbandonOutcome.SETTLED
        assert _status(book, order) is OrderStatus.PAID

    def test_order_paid_while_its_session_was_expired_stays_paid(
        self, sales, book, types, orders, payments, monkeypatch
    ):
        order = _order(orders, types.add(), stripe_checkout_session_id="cs_1")

        def paid_meanwhile(**_stripe_call):
            orders.move(
                pk=order.pk,
                to=OrderStatus.PAID,
                allowed_from=frozenset({OrderStatus.PENDING}),
                changes={},
            )

        monkeypatch.setattr(payments, "expire_checkout", paid_meanwhile)

        outcome = sales.abandon_checkout(
            event_id=EVENT_ID, reference=order.reference, viewer_id=BUYER_ID
        )

        assert outcome is AbandonOutcome.SETTLED
        assert _status(book, order) is OrderStatus.PAID


class TestClaimOrder:
    def test_claimed_guest_order_becomes_the_accounts_alone(
        self, sales, book, types, orders
    ):
        regular = types.add()
        order = _guest_order(orders, regular, status=OrderStatus.PAID)
        orders.issue_tickets(
            order=order, tickets=[{"ticket_type_id": regular.pk, "code": "AAAA"}]
        )

        outcome = sales.claim_order(
            event_id=EVENT_ID, reference=order.reference, user_id=BUYER_ID
        )

        assert outcome is ClaimOutcome.CLAIMED
        assert book.orders[order.pk].buyer_id == BUYER_ID
        assert [
            ticket.code
            for ticket in sales.owned_tickets(sphere_id=SPHERE_ID, holder_id=BUYER_ID)
        ] == ["AAAA"]
        assert sales.shop(event=book.event, viewer_id=BUYER_ID).viewer_ticket_count == 1
        for viewer in (None, OTHER_BUYER_ID):
            with pytest.raises(NotFoundError):
                sales.order(
                    event_id=EVENT_ID, reference=order.reference, viewer_id=viewer
                )

    def test_claiming_your_own_order_again_changes_nothing(
        self, sales, book, types, orders
    ):
        order = _order(orders, types.add())

        outcome = sales.claim_order(
            event_id=EVENT_ID, reference=order.reference, user_id=BUYER_ID
        )

        assert outcome is ClaimOutcome.ALREADY_YOURS
        assert book.orders[order.pk] == order

    @pytest.mark.parametrize(
        ("event_id", "reference", "holder"),
        (
            pytest.param(EVENT_ID, "ref1", OTHER_BUYER_ID, id="held-by-another"),
            pytest.param(OTHER_EVENT_ID, "ref1", None, id="another-event"),
            pytest.param(EVENT_ID, "nope", None, id="unknown-reference"),
        ),
    )
    def test_order_out_of_reach_is_not_claimed(
        self, sales, book, types, orders, event_id, reference, holder
    ):
        order = _order(orders, types.add(), buyer_id=holder)

        with pytest.raises(NotFoundError):
            sales.claim_order(event_id=event_id, reference=reference, user_id=BUYER_ID)
        assert book.orders[order.pk] == order


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
            SubscriptionEvent(subscription_id="sub_1", customer_id="cus_1"),
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
        self, sales, book, types, orders, payments, mailer
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
        assert mailer.sent == []

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
        self, sales, book, types, orders, payments, mailer, given_up
    ):
        order = _order(
            orders, types.add(), stripe_checkout_session_id="cs_1", status=given_up
        )

        outcome = _deliver(
            sales, payments, _checkout(CheckoutStage.COMPLETED, email=_GUEST_EMAIL)
        )

        assert outcome is WebhookOutcome.REFUNDED
        assert payments.refunded == ["pi_1"]
        assert book.orders[order.pk] == order
        assert mailer.sent == []

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

        assert outcome is WebhookOutcome.PARTLY_REFUNDED
        assert book.orders[order.pk] == paid
        owned = sales.owned_tickets(sphere_id=SPHERE_ID, holder_id=BUYER_ID)
        assert [ticket.code for ticket in owned] == [
            ticket.code for ticket in paid.tickets
        ]


class TestOrderMail:
    def test_paid_guest_order_keeps_the_email_and_is_mailed_once(
        self, sales, book, types, orders, payments, mailer
    ):
        order = _guest_order(orders, types.add(), stripe_checkout_session_id="cs_1")
        completed = _checkout(CheckoutStage.COMPLETED, email=_GUEST_EMAIL)

        first = _deliver(sales, payments, completed)
        again = _deliver(sales, payments, completed)

        assert (first, again) == (WebhookOutcome.PAID, WebhookOutcome.STALE)
        assert book.orders[order.pk].email == _GUEST_EMAIL
        assert mailer.sent == [
            OrderLinkMail(
                email=_GUEST_EMAIL,
                event_id=EVENT_ID,
                event_name=book.event.name,
                event_slug=book.event.slug,
                reference=order.reference,
                claimable=True,
            )
        ]

    def test_delayed_payment_is_mailed_when_checkout_completes_not_again(
        self, sales, book, types, orders, payments, mailer
    ):
        order = _guest_order(orders, types.add(), stripe_checkout_session_id="cs_1")

        _deliver(
            sales,
            payments,
            _checkout(CheckoutStage.COMPLETED, paid=False, email=_GUEST_EMAIL),
        )
        awaiting = book.orders[order.pk]
        mailed_while_awaiting = list(mailer.sent)
        _deliver(sales, payments, _checkout(CheckoutStage.ASYNC_SUCCEEDED))

        assert awaiting.email == _GUEST_EMAIL
        assert [mail.reference for mail in mailed_while_awaiting] == [order.reference]
        assert _status(book, order) is OrderStatus.PAID
        assert mailer.sent == mailed_while_awaiting

    @pytest.mark.parametrize(
        ("typed", "kept"),
        (("", "buyer@example.com"), ("typed@example.com", "typed@example.com")),
        ids=("account-email", "typed-in-checkout"),
    )
    def test_account_buyer_is_mailed_where_checkout_last_heard_from_them(
        self, sales, book, types, orders, payments, mailer, typed, kept
    ):
        order = _order(orders, types.add(), stripe_checkout_session_id="cs_1")

        _deliver(sales, payments, _checkout(CheckoutStage.COMPLETED, email=typed))

        assert book.orders[order.pk].email == kept
        assert [(mail.email, mail.claimable) for mail in mailer.sent] == [(kept, False)]

    def test_order_without_any_email_is_paid_and_not_mailed(
        self, sales, book, types, orders, payments, mailer, caplog
    ):
        order = _guest_order(orders, types.add(), stripe_checkout_session_id="cs_1")

        with caplog.at_level(logging.WARNING, logger=_TICKETS_LOGGER):
            outcome = _deliver(sales, payments, _checkout(CheckoutStage.COMPLETED))

        assert outcome is WebhookOutcome.PAID
        assert len(book.orders[order.pk].tickets) == order.ticket_count
        assert mailer.sent == []
        assert caplog.messages == [
            f"Ticket order has no email to send it to: {order.pk}"
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

    def test_page_prices_at_the_spheres_deal_rate(self, panel, types, plans):
        plans.add(ticket_fee_bps=_DEAL_FEE_BPS)
        types.add(price=_PRICE)

        page = panel.page(sphere_id=SPHERE_ID, event_id=EVENT_ID)

        assert page.platform_fee_percent == Decimal("1.5")
        assert page.rows[0].fees.platform_fee == _DEAL_FEE_ON_TWO // 2

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
        assert sales.owned_tickets(sphere_id=SPHERE_ID, holder_id=BUYER_ID) == []
