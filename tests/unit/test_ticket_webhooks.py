"""Ticket sales: Stripe's webhook, and the order mail it sends.

Ways the service could fail, each pinned below:

Webhook
- A redelivered or reordered event moves an order backwards or twice.
- An event for someone else's session, account or payment intent touches ours.
- A partial refund voids the tickets.
- A delayed payment issues tickets before it settles.
- Money taken for an order we gave up on is kept, or tickets are issued for it.
- A late payment that cannot be refunded is reported as refunded.
- Seats resold while a payment was late go unnoticed.
- A guest's order keeps its network once it holds no seats, or forgets it
  while a bank transfer still holds them, so the guest hold limit misses it.

Order mail
- A guest's email from Checkout is not kept on the order.
- The mail is not sent as the order leaves Checkout, or only when one
  particular event moves it, so a delayed payment's success that Stripe
  delivers before "completed" goes unmailed.
- It is sent again on a redelivery or when the money settles, or for an order
  that failed, expired, or was refunded as a late payment.
- It says the tickets are there while the money is still on its way.
- An order with no email anywhere crashes the webhook instead of skipping mail.
"""

import logging
from datetime import timedelta

import pytest

from ludamus.pacts.payment_api import (
    AccountEvent,
    AccountState,
    CheckoutStage,
    PaymentProviderError,
    RefundEvent,
    SubscriptionEvent,
    UnhandledEvent,
    WebhookOutcome,
)
from ludamus.pacts.tickets import (
    TICKET_CODE_LENGTH,
    OrderLinkMail,
    OrderMailEvent,
    OrderStatus,
)
from tests.unit.ticket_fakes import (
    ACCOUNT_ID,
    BUYER_EMAIL,
    BUYER_ID,
    EVENT_ID,
    GUEST_EMAIL,
    NOW,
    OTHER_BUYER_ID,
    SPHERE_ID,
    TICKETS_LOGGER,
    add_guest_order,
    add_order,
    checkout_event,
    deliver,
    status_of,
)

pytest_plugins = ("tests.unit.ticket_fixtures",)

_CODE_ALPHABET = set("ABCDEFGHJKMNPQRSTUVWXYZ23456789")
_GUEST_CLIENT = "client-a"


class TestWebhook:
    def test_known_account_update_is_stored(self, sales, accounts, payments):
        accounts.add(charges_enabled=False)
        state = AccountState(
            details_submitted=True, charges_enabled=True, payouts_enabled=False
        )

        outcome = deliver(
            sales, payments, AccountEvent(account_id=ACCOUNT_ID, state=state)
        )

        assert outcome is WebhookOutcome.ACCOUNT_UPDATED
        assert accounts.rows[SPHERE_ID].charges_enabled

    def test_unknown_account_update_is_not_ours(self, sales, accounts, payments):
        accounts.add(charges_enabled=False)
        state = AccountState(
            details_submitted=True, charges_enabled=True, payouts_enabled=True
        )

        outcome = deliver(
            sales, payments, AccountEvent(account_id="acct_other", state=state)
        )

        assert outcome is WebhookOutcome.NOT_OURS
        assert not accounts.rows[SPHERE_ID].charges_enabled

    @pytest.mark.parametrize(
        "event",
        (
            SubscriptionEvent(subscription_id="sub_1", customer_id="cus_1"),
            UnhandledEvent(type="customer.created"),
            checkout_event(CheckoutStage.COMPLETED, session_id="cs_other"),
            RefundEvent(payment_intent_id="pi_other", fully_refunded=True),
        ),
    )
    def test_event_about_nothing_of_ours_changes_nothing(
        self, sales, book, types, orders, payments, event
    ):
        order = add_order(orders, types.add(), stripe_checkout_session_id="cs_1")

        assert deliver(sales, payments, event) is WebhookOutcome.NOT_OURS
        assert book.orders[order.pk] == order

    def test_paid_checkout_issues_one_code_per_seat(
        self, sales, book, types, orders, payments
    ):
        order = add_order(orders, types.add(), stripe_checkout_session_id="cs_1")

        outcome = deliver(sales, payments, checkout_event(CheckoutStage.COMPLETED))

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
        order = add_order(orders, types.add(), stripe_checkout_session_id="cs_1")
        deliver(sales, payments, checkout_event(CheckoutStage.COMPLETED))
        issued = book.orders[order.pk]

        outcome = deliver(
            sales, payments, checkout_event(CheckoutStage.ASYNC_SUCCEEDED)
        )

        assert outcome is WebhookOutcome.STALE
        assert book.orders[order.pk] == issued
        assert payments.refunded == []

    def test_delayed_payment_holds_seats_until_it_settles(
        self, sales, book, types, orders, payments
    ):
        order = add_order(orders, types.add(), stripe_checkout_session_id="cs_1")

        completed = deliver(
            sales, payments, checkout_event(CheckoutStage.COMPLETED, paid=False)
        )
        awaiting = book.orders[order.pk]
        settled = deliver(
            sales, payments, checkout_event(CheckoutStage.ASYNC_SUCCEEDED)
        )

        assert completed is WebhookOutcome.AWAITING_PAYMENT
        assert awaiting.status is OrderStatus.AWAITING_PAYMENT
        assert awaiting.stripe_payment_intent_id == "pi_1"
        assert awaiting.tickets == []
        assert settled is WebhookOutcome.PAID
        assert len(book.orders[order.pk].tickets) == order.ticket_count

    @pytest.mark.parametrize(
        ("stage", "paid", "status", "guest_client"),
        (
            pytest.param(
                CheckoutStage.COMPLETED, True, OrderStatus.PAID, "", id="paid"
            ),
            pytest.param(
                CheckoutStage.COMPLETED,
                False,
                OrderStatus.AWAITING_PAYMENT,
                _GUEST_CLIENT,
                id="awaiting-payment",
            ),
            pytest.param(
                CheckoutStage.EXPIRED, False, OrderStatus.EXPIRED, "", id="expired"
            ),
            pytest.param(
                CheckoutStage.ASYNC_FAILED, False, OrderStatus.FAILED, "", id="failed"
            ),
        ),
    )
    def test_guest_order_keeps_its_network_only_while_it_holds_seats(
        self, sales, book, types, orders, payments, stage, paid, status, guest_client
    ):
        order = add_guest_order(
            orders,
            types.add(),
            stripe_checkout_session_id="cs_1",
            guest_client=_GUEST_CLIENT,
        )

        deliver(sales, payments, checkout_event(stage, paid=paid))

        assert status_of(book, order) is status
        assert book.guest_clients[order.pk] == guest_client

    def test_failed_delayed_payment_is_final(
        self, sales, book, types, orders, payments, mailer
    ):
        order = add_order(
            orders,
            types.add(),
            stripe_checkout_session_id="cs_1",
            status=OrderStatus.AWAITING_PAYMENT,
        )

        failed = deliver(sales, payments, checkout_event(CheckoutStage.ASYNC_FAILED))
        late_completion = deliver(
            sales, payments, checkout_event(CheckoutStage.COMPLETED, paid=False)
        )

        assert (failed, late_completion) == (
            WebhookOutcome.FAILED,
            WebhookOutcome.STALE,
        )
        assert status_of(book, order) is OrderStatus.FAILED
        assert mailer.sent == []

    @pytest.mark.parametrize(
        ("stage", "outcome", "status"),
        (
            (CheckoutStage.EXPIRED, WebhookOutcome.EXPIRED, OrderStatus.EXPIRED),
            (CheckoutStage.ASYNC_FAILED, WebhookOutcome.FAILED, OrderStatus.FAILED),
        ),
    )
    def test_checkout_that_ends_unpaid_releases_the_order_once_unmailed(
        self, sales, book, types, orders, payments, mailer, stage, outcome, status
    ):
        order = add_order(orders, types.add(), stripe_checkout_session_id="cs_1")

        first = deliver(sales, payments, checkout_event(stage))
        again = deliver(sales, payments, checkout_event(stage))

        assert (first, again) == (outcome, WebhookOutcome.STALE)
        assert status_of(book, order) is status
        assert mailer.sent == []

    @pytest.mark.parametrize("given_up", (OrderStatus.EXPIRED, OrderStatus.FAILED))
    def test_payment_for_an_order_given_up_on_is_refunded(
        self, sales, book, types, orders, payments, mailer, given_up
    ):
        order = add_order(
            orders, types.add(), stripe_checkout_session_id="cs_1", status=given_up
        )

        outcome = deliver(
            sales, payments, checkout_event(CheckoutStage.COMPLETED, email=GUEST_EMAIL)
        )

        assert outcome is WebhookOutcome.REFUNDED
        assert payments.refunded == ["pi_1"]
        assert book.orders[order.pk] == order
        assert mailer.sent == []

    def test_late_payment_stripe_will_not_refund_fails_the_delivery(
        self, sales, book, types, orders, payments
    ):
        order = add_order(
            orders,
            types.add(),
            stripe_checkout_session_id="cs_1",
            status=OrderStatus.EXPIRED,
        )
        payments.down.add("refund_once")

        with pytest.raises(PaymentProviderError):
            deliver(sales, payments, checkout_event(CheckoutStage.COMPLETED))

        assert payments.refunded == []
        assert book.orders[order.pk] == order

    def test_payment_after_the_seats_were_resold_is_flagged_as_oversold(
        self, sales, types, orders, payments, caplog
    ):
        capped = types.add(quantity=2)
        uncapped = types.add()
        add_order(
            orders,
            capped,
            stripe_checkout_session_id="cs_late",
            hold_until=NOW - timedelta(hours=2),
        )
        add_order(orders, capped, status=OrderStatus.PAID, buyer_id=OTHER_BUYER_ID)
        add_order(orders, uncapped, status=OrderStatus.PAID, buyer_id=OTHER_BUYER_ID)

        with caplog.at_level(logging.WARNING, logger=TICKETS_LOGGER):
            outcome = deliver(
                sales,
                payments,
                checkout_event(CheckoutStage.COMPLETED, session_id="cs_late"),
            )

        assert outcome is WebhookOutcome.PAID
        assert caplog.messages == [
            f"Ticket type oversold: event={EVENT_ID} type={capped.pk} sold=4 cap=2"
        ]

    def test_full_refund_voids_the_tickets_once(
        self, sales, book, types, orders, payments
    ):
        order = add_order(orders, types.add(), stripe_checkout_session_id="cs_1")
        deliver(sales, payments, checkout_event(CheckoutStage.COMPLETED))
        refund = RefundEvent(payment_intent_id="pi_1", fully_refunded=True)

        first = deliver(sales, payments, refund)
        refunded = book.orders[order.pk]
        again = deliver(sales, payments, refund)

        assert (first, again) == (WebhookOutcome.REFUNDED, WebhookOutcome.STALE)
        assert refunded.status is OrderStatus.REFUNDED
        assert refunded.refunded_at is not None
        assert book.orders[order.pk] == refunded
        assert sales.owned_tickets(sphere_id=SPHERE_ID, holder_id=BUYER_ID) == []

    def test_partial_refund_keeps_the_tickets(
        self, sales, book, types, orders, payments
    ):
        order = add_order(orders, types.add(), stripe_checkout_session_id="cs_1")
        deliver(sales, payments, checkout_event(CheckoutStage.COMPLETED))
        paid = book.orders[order.pk]

        outcome = deliver(
            sales, payments, RefundEvent(payment_intent_id="pi_1", fully_refunded=False)
        )

        assert outcome is WebhookOutcome.PARTLY_REFUNDED
        assert book.orders[order.pk] == paid
        owned = sales.owned_tickets(sphere_id=SPHERE_ID, holder_id=BUYER_ID)
        assert [ticket.code for ticket in owned] == [
            ticket.code for ticket in paid.tickets
        ]


class TestOrderMail:
    @staticmethod
    def _mail(book, order, *, email=GUEST_EMAIL, paid=True, is_guest=True):
        return OrderLinkMail(
            order_pk=order.pk,
            email=email,
            event=OrderMailEvent(
                pk=EVENT_ID, name=book.event.name, slug=book.event.slug
            ),
            reference=order.reference,
            paid=paid,
            is_guest=is_guest,
        )

    def test_paid_guest_order_keeps_the_email_and_is_mailed_once(
        self, sales, book, types, orders, payments, mailer
    ):
        order = add_guest_order(orders, types.add(), stripe_checkout_session_id="cs_1")
        completed = checkout_event(CheckoutStage.COMPLETED, email=GUEST_EMAIL)

        first = deliver(sales, payments, completed)
        again = deliver(sales, payments, completed)

        assert (first, again) == (WebhookOutcome.PAID, WebhookOutcome.STALE)
        assert book.orders[order.pk].email == GUEST_EMAIL
        assert mailer.sent == [self._mail(book, order)]

    def test_delayed_payment_is_mailed_unpaid_when_checkout_completes_not_again(
        self, sales, book, types, orders, payments, mailer
    ):
        order = add_guest_order(orders, types.add(), stripe_checkout_session_id="cs_1")

        deliver(
            sales,
            payments,
            checkout_event(CheckoutStage.COMPLETED, paid=False, email=GUEST_EMAIL),
        )
        awaiting = book.orders[order.pk]
        deliver(sales, payments, checkout_event(CheckoutStage.ASYNC_SUCCEEDED))

        assert awaiting.email == GUEST_EMAIL
        assert status_of(book, order) is OrderStatus.PAID
        assert mailer.sent == [self._mail(book, order, paid=False)]

    def test_delayed_payment_settled_before_checkout_completes_is_mailed_paid_once(
        self, sales, book, types, orders, payments, mailer
    ):
        order = add_guest_order(orders, types.add(), stripe_checkout_session_id="cs_1")

        settled = deliver(
            sales,
            payments,
            checkout_event(CheckoutStage.ASYNC_SUCCEEDED, email=GUEST_EMAIL),
        )
        completed = deliver(
            sales,
            payments,
            checkout_event(CheckoutStage.COMPLETED, paid=False, email=GUEST_EMAIL),
        )

        assert (settled, completed) == (WebhookOutcome.PAID, WebhookOutcome.STALE)
        assert status_of(book, order) is OrderStatus.PAID
        assert mailer.sent == [self._mail(book, order)]

    @pytest.mark.parametrize(
        ("typed", "kept"),
        (("", BUYER_EMAIL), ("typed@example.com", "typed@example.com")),
        ids=("account-email", "typed-in-checkout"),
    )
    def test_account_buyer_is_mailed_where_checkout_last_heard_from_them(
        self, sales, book, types, orders, payments, mailer, typed, kept
    ):
        order = add_order(orders, types.add(), stripe_checkout_session_id="cs_1")

        deliver(sales, payments, checkout_event(CheckoutStage.COMPLETED, email=typed))

        assert book.orders[order.pk].email == kept
        assert mailer.sent == [self._mail(book, order, email=kept, is_guest=False)]

    def test_order_without_any_email_is_paid_and_not_mailed(
        self, sales, book, types, orders, payments, mailer, caplog
    ):
        order = add_guest_order(orders, types.add(), stripe_checkout_session_id="cs_1")

        with caplog.at_level(logging.WARNING, logger=TICKETS_LOGGER):
            outcome = deliver(sales, payments, checkout_event(CheckoutStage.COMPLETED))

        assert outcome is WebhookOutcome.PAID
        assert len(book.orders[order.pk].tickets) == order.ticket_count
        assert mailer.sent == []
        assert caplog.messages == [
            f"Ticket order has no email to send it to: {order.pk}"
        ]
