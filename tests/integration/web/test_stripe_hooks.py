"""Stripe's webhooks, end to end: signature, idempotency, and what each changes.

How it could go wrong: a forged or replayed delivery is acted on; a redelivery
issues tickets twice; a paid order issues the wrong number of tickets or none;
a refund leaves tickets valid; an unpaid (delayed) checkout issues tickets; an
expiry kills a paid order; the yearly plan is switched by a webhook for a plan
a maintainer recorded by hand.
"""

from datetime import UTC, datetime, timedelta
from http import HTTPStatus

import pytest
from django.urls import reverse

from ludamus.links.db.django.models import (
    PayoutAccount,
    SpherePlan,
    Ticket,
    TicketOrder,
)
from ludamus.pacts.billing import PlanKind, PlanSource
from ludamus.pacts.tickets import OrderStatus
from tests.integration.stripe_helpers import (
    ACCOUNT_ID,
    BILLING_SECRET,
    CONNECT_SECRET,
    connected_account,
    event_payload,
    order,
    post_hook,
    ticket_type,
)
from tests.integration.utils import assert_response

pytestmark = pytest.mark.usefixtures("stripe_settings")

CONNECT_URL = reverse("stripe-connect-hook")
BILLING_URL = reverse("stripe-billing-hook")
CUSTOMER_ID = "cus_test_sphere"
PERIOD_END = datetime(2027, 10, 23, 12, tzinfo=UTC)


def _checkout(session_id="cs_test_1", *, paid=True, mode="payment", **extra):
    return {
        "id": session_id,
        "object": "checkout.session",
        "mode": mode,
        "payment_status": "paid" if paid else "unpaid",
        "payment_intent": "pi_test_1",
        **extra,
    }


def _connect(client, event_type, obj, *, event_id="evt_1"):
    return post_hook(
        client,
        CONNECT_URL,
        event_payload(event_type, obj, event_id=event_id, account=ACCOUNT_ID),
        CONNECT_SECRET,
    )


@pytest.fixture(name="paid_setup")
def paid_setup_fixture(event, active_user):
    connected_account(event.sphere)
    weekend = ticket_type(event)
    saturday = ticket_type(event, name="Saturday", price=3000)
    return order(event, buyer=active_user, lines=[(weekend, 2), (saturday, 1)])


class TestSignature:
    def test_refuses_a_payload_signed_with_another_secret(self, client, paid_setup):
        response = post_hook(
            client,
            CONNECT_URL,
            event_payload("checkout.session.completed", _checkout()),
            "whsec_someone_else",
        )

        assert_response(
            response,
            HTTPStatus.BAD_REQUEST,
            json={"error": "Invalid signature or payload."},
        )
        assert TicketOrder.objects.get(pk=paid_setup.pk).status == OrderStatus.PENDING

    def test_refuses_everything_when_no_secret_is_configured(
        self, client, paid_setup, settings
    ):
        settings.STRIPE_CONNECT_WEBHOOK_SECRET = ""

        response = _connect(client, "checkout.session.completed", _checkout())

        assert_response(
            response,
            HTTPStatus.BAD_REQUEST,
            json={"error": "Invalid signature or payload."},
        )
        assert not Ticket.objects.exists()

    def test_billing_secret_does_not_open_the_connect_endpoint(
        self, client, paid_setup
    ):
        response = post_hook(
            client,
            CONNECT_URL,
            event_payload("checkout.session.completed", _checkout()),
            BILLING_SECRET,
        )

        assert_response(
            response,
            HTTPStatus.BAD_REQUEST,
            json={"error": "Invalid signature or payload."},
        )


class TestCheckoutCompleted:
    def test_paid_checkout_pays_the_order_and_issues_a_ticket_per_seat(
        self, client, paid_setup, active_user
    ):
        response = _connect(client, "checkout.session.completed", _checkout())

        assert_response(response, HTTPStatus.OK, json={"outcome": "paid"})
        paid = TicketOrder.objects.get(pk=paid_setup.pk)
        assert paid.status == OrderStatus.PAID
        assert paid.stripe_payment_intent_id == "pi_test_1"
        assert paid.paid_at is not None
        tickets = Ticket.objects.filter(order=paid)
        assert sorted(tickets.values_list("ticket_type__name", flat=True)) == [
            "Saturday",
            "Weekend pass",
            "Weekend pass",
        ]
        assert {ticket.holder_id for ticket in tickets} == {active_user.pk}
        assert len({ticket.code for ticket in tickets}) == 1 + 1 + 1

    def test_redelivery_finds_the_order_paid_and_changes_nothing(
        self, client, paid_setup
    ):
        _connect(client, "checkout.session.completed", _checkout())

        response = _connect(client, "checkout.session.completed", _checkout())

        assert_response(response, HTTPStatus.OK, json={"outcome": "stale"})
        assert Ticket.objects.filter(order=paid_setup).count() == 1 + 1 + 1

    def test_second_event_for_a_paid_order_issues_nothing_more(
        self, client, paid_setup
    ):
        _connect(client, "checkout.session.completed", _checkout())

        response = _connect(
            client,
            "checkout.session.async_payment_succeeded",
            _checkout(),
            event_id="evt_2",
        )

        assert_response(response, HTTPStatus.OK, json={"outcome": "stale"})
        assert Ticket.objects.filter(order=paid_setup).count() == 1 + 1 + 1

    def test_delayed_payment_holds_seats_without_tickets(self, client, paid_setup):
        response = _connect(client, "checkout.session.completed", _checkout(paid=False))

        assert_response(response, HTTPStatus.OK, json={"outcome": "awaiting_payment"})
        assert (
            TicketOrder.objects.get(pk=paid_setup.pk).status
            == OrderStatus.AWAITING_PAYMENT
        )
        assert not Ticket.objects.exists()

    def test_delayed_payment_that_fails_frees_the_order(self, client, paid_setup):
        _connect(client, "checkout.session.completed", _checkout(paid=False))

        response = _connect(
            client,
            "checkout.session.async_payment_failed",
            _checkout(paid=False),
            event_id="evt_2",
        )

        assert_response(response, HTTPStatus.OK, json={"outcome": "failed"})
        assert TicketOrder.objects.get(pk=paid_setup.pk).status == OrderStatus.FAILED

    def test_payment_for_an_abandoned_order_issues_nothing(self, client, paid_setup):
        TicketOrder.objects.filter(pk=paid_setup.pk).update(status=OrderStatus.EXPIRED)

        response = _connect(client, "checkout.session.completed", _checkout())

        assert_response(response, HTTPStatus.OK, json={"outcome": "stale"})
        assert TicketOrder.objects.get(pk=paid_setup.pk).status == OrderStatus.EXPIRED
        assert not Ticket.objects.exists()

    def test_unknown_session_is_acknowledged(self, client, paid_setup):
        response = _connect(
            client, "checkout.session.completed", _checkout("cs_not_ours")
        )

        assert_response(response, HTTPStatus.OK, json={"outcome": "not_ours"})
        assert not Ticket.objects.exists()


class TestExpiredAndRefunded:
    def test_expiry_releases_a_pending_order(self, client, paid_setup):
        response = _connect(client, "checkout.session.expired", _checkout(paid=False))

        assert_response(response, HTTPStatus.OK, json={"outcome": "expired"})
        assert TicketOrder.objects.get(pk=paid_setup.pk).status == OrderStatus.EXPIRED

    def test_expiry_never_undoes_a_paid_order(self, client, paid_setup):
        _connect(client, "checkout.session.completed", _checkout())

        _connect(
            client, "checkout.session.expired", _checkout(paid=False), event_id="evt_2"
        )

        assert TicketOrder.objects.get(pk=paid_setup.pk).status == OrderStatus.PAID

    def test_full_refund_voids_the_tickets(self, client, paid_setup):
        _connect(client, "checkout.session.completed", _checkout())

        response = _connect(
            client,
            "charge.refunded",
            {"id": "ch_1", "payment_intent": "pi_test_1", "refunded": True},
            event_id="evt_2",
        )

        assert_response(response, HTTPStatus.OK, json={"outcome": "refunded"})
        refunded = TicketOrder.objects.get(pk=paid_setup.pk)
        assert refunded.status == OrderStatus.REFUNDED
        assert refunded.refunded_at is not None
        assert set(
            Ticket.objects.filter(order=refunded).values_list("is_void", flat=True)
        ) == {True}

    def test_partial_refund_leaves_the_order_alone(self, client, paid_setup):
        _connect(client, "checkout.session.completed", _checkout())

        response = _connect(
            client,
            "charge.refunded",
            {"id": "ch_1", "payment_intent": "pi_test_1", "refunded": False},
            event_id="evt_2",
        )

        assert_response(response, HTTPStatus.OK, json={"outcome": "not_ours"})
        assert TicketOrder.objects.get(pk=paid_setup.pk).status == OrderStatus.PAID


class TestAccountUpdated:
    def test_records_what_stripe_now_allows(self, client, sphere):
        account = connected_account(sphere, charges_enabled=False)

        response = _connect(
            client,
            "account.updated",
            {
                "id": ACCOUNT_ID,
                "object": "account",
                "details_submitted": True,
                "charges_enabled": True,
                "payouts_enabled": False,
            },
        )

        assert_response(response, HTTPStatus.OK, json={"outcome": "account_updated"})
        account.refresh_from_db()
        assert (
            account.details_submitted,
            account.charges_enabled,
            account.payouts_enabled,
        ) == (True, True, False)

    def test_account_we_do_not_know_changes_nothing(self, client):
        response = _connect(
            client, "account.updated", {"id": "acct_stranger", "charges_enabled": True}
        )

        assert_response(response, HTTPStatus.OK, json={"outcome": "not_ours"})
        assert not PayoutAccount.objects.exists()


def _billing(client, event_type, obj, *, event_id="evt_b1"):
    return post_hook(
        client,
        BILLING_URL,
        event_payload(event_type, obj, event_id=event_id),
        BILLING_SECRET,
    )


def _invoice():
    return {
        "id": "in_1",
        "object": "invoice",
        "customer": CUSTOMER_ID,
        "parent": {
            "type": "subscription_details",
            "subscription_details": {"subscription": "sub_1"},
        },
        "lines": {"data": [{"period": {"end": int(PERIOD_END.timestamp())}}]},
    }


class TestYearlyPlan:
    @pytest.fixture(name="customer")
    def customer_fixture(self, sphere):
        return SpherePlan.objects.create(sphere=sphere, stripe_customer_id=CUSTOMER_ID)

    def test_paid_invoice_puts_the_sphere_on_the_yearly_plan(self, client, customer):
        response = _billing(client, "invoice.paid", _invoice())

        assert_response(response, HTTPStatus.OK, json={"outcome": "renewed"})
        customer.refresh_from_db()
        assert (
            customer.kind,
            customer.source,
            customer.paid_until,
            customer.stripe_subscription_id,
        ) == (PlanKind.WHITE_GLOVE, PlanSource.STRIPE, PERIOD_END, "sub_1")

    def test_cancelled_subscription_returns_to_the_standard_plan(
        self, client, customer
    ):
        _billing(client, "invoice.paid", _invoice())

        response = _billing(
            client,
            "customer.subscription.deleted",
            {"id": "sub_1", "customer": CUSTOMER_ID, "status": "canceled"},
            event_id="evt_b2",
        )

        assert_response(response, HTTPStatus.OK, json={"outcome": "ended"})
        customer.refresh_from_db()
        assert customer.kind == PlanKind.STANDARD

    def test_plan_recorded_by_hand_is_left_alone(self, client, customer):
        paid_until = datetime.now(UTC) + timedelta(days=200)
        SpherePlan.objects.filter(pk=customer.pk).update(
            kind=PlanKind.WHITE_GLOVE, source=PlanSource.MANUAL, paid_until=paid_until
        )

        response = _billing(
            client,
            "customer.subscription.deleted",
            {"id": "sub_1", "customer": CUSTOMER_ID, "status": "canceled"},
        )

        assert_response(response, HTTPStatus.OK, json={"outcome": "stale"})
        customer.refresh_from_db()
        assert (customer.kind, customer.paid_until) == (
            PlanKind.WHITE_GLOVE,
            paid_until,
        )

    def test_unknown_customer_changes_nothing(self, client, customer):
        response = _billing(
            client, "invoice.paid", _invoice() | {"customer": "cus_stranger"}
        )

        assert_response(response, HTTPStatus.OK, json={"outcome": "not_ours"})
        customer.refresh_from_db()
        assert customer.kind == PlanKind.STANDARD

    def test_invoice_for_an_older_subscription_changes_nothing(self, client, customer):
        SpherePlan.objects.filter(pk=customer.pk).update(
            kind=PlanKind.STANDARD, stripe_subscription_id="sub_new"
        )

        response = _billing(client, "invoice.paid", _invoice())

        assert_response(response, HTTPStatus.OK, json={"outcome": "stale"})
        customer.refresh_from_db()
        assert customer.kind == PlanKind.STANDARD

    def test_one_off_invoice_is_not_the_yearly_plan(self, client, customer):
        response = _billing(client, "invoice.paid", _invoice() | {"parent": None})

        assert_response(response, HTTPStatus.OK, json={"outcome": "not_ours"})
        customer.refresh_from_db()
        assert customer.kind == PlanKind.STANDARD

    def test_checkout_after_its_invoice_keeps_the_paid_date(self, client, customer):
        _billing(client, "invoice.paid", _invoice())

        response = _billing(
            client,
            "checkout.session.completed",
            {
                "id": "cs_plan",
                "mode": "subscription",
                "payment_status": "paid",
                "customer": CUSTOMER_ID,
                "subscription": "sub_1",
            },
            event_id="evt_b2",
        )

        assert_response(response, HTTPStatus.OK, json={"outcome": "stale"})
        customer.refresh_from_db()
        assert customer.paid_until == PERIOD_END
