"""Stripe's webhooks, end to end: signature, idempotency, and what each changes.

How it could go wrong: a forged or replayed delivery is acted on; a redelivery
issues tickets twice; a paid order issues the wrong number of tickets or none;
a refund leaves tickets valid; an unpaid (delayed) checkout issues tickets; an
expiry kills a paid order; the yearly plan is switched by a webhook for a plan
a maintainer recorded by hand.
"""

from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from urllib.parse import parse_qs

import pytest
import responses
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
    API,
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

    def test_failure_that_beats_its_completion_frees_the_seats(
        self, client, paid_setup
    ):
        _connect(client, "checkout.session.async_payment_failed", _checkout(paid=False))

        response = _connect(
            client,
            "checkout.session.completed",
            _checkout(paid=False),
            event_id="evt_2",
        )

        assert_response(response, HTTPStatus.OK, json={"outcome": "stale"})
        assert TicketOrder.objects.get(pk=paid_setup.pk).status == OrderStatus.FAILED

    def test_payment_for_an_abandoned_order_goes_straight_back(
        self, client, paid_setup, stripe_api
    ):
        TicketOrder.objects.filter(pk=paid_setup.pk).update(status=OrderStatus.EXPIRED)
        stripe_api.add(
            responses.POST, f"{API}/refunds", json={"id": "re_1", "object": "refund"}
        )

        response = _connect(client, "checkout.session.completed", _checkout())

        assert_response(response, HTTPStatus.OK, json={"outcome": "refunded"})
        assert TicketOrder.objects.get(pk=paid_setup.pk).status == OrderStatus.EXPIRED
        assert not Ticket.objects.exists()
        sent = parse_qs(stripe_api.calls[0].request.body)
        assert (sent["payment_intent"], sent["refund_application_fee"]) == (
            ["pi_test_1"],
            ["true"],
        )
        assert stripe_api.calls[0].request.headers["Stripe-Account"] == ACCOUNT_ID

    def test_late_payment_stripe_will_not_refund_asks_for_a_retry(
        self, client, paid_setup, stripe_api
    ):
        TicketOrder.objects.filter(pk=paid_setup.pk).update(status=OrderStatus.FAILED)
        stripe_api.add(
            responses.POST,
            f"{API}/refunds",
            status=HTTPStatus.BAD_REQUEST,
            json={"error": {"message": "nope", "type": "invalid_request_error"}},
        )

        response = _connect(client, "checkout.session.completed", _checkout())

        assert_response(
            response,
            HTTPStatus.SERVICE_UNAVAILABLE,
            json={"error": "Stripe could not be reached; retry later."},
        )
        assert TicketOrder.objects.get(pk=paid_setup.pk).status == OrderStatus.FAILED
        assert not Ticket.objects.exists()
        assert (
            stripe_api.calls[0]
            .request.headers["Idempotency-Key"]
            .endswith("-refund-pi_test_1")
        )

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


def _subscription_changed(client, subscription_id="sub_1"):
    return _billing(
        client,
        "customer.subscription.updated",
        {"id": subscription_id, "object": "subscription", "status": "whatever"},
    )


def _stripe_says(
    stripe_api,
    *,
    subscription_id="sub_1",
    status="active",
    customer=CUSTOMER_ID,
    period_end=PERIOD_END,
):
    stripe_api.add(
        responses.GET,
        f"{API}/subscriptions/{subscription_id}",
        json={
            "id": subscription_id,
            "object": "subscription",
            "customer": customer,
            "status": status,
            "items": {
                "object": "list",
                "data": [
                    {
                        "id": "si_1",
                        "object": "subscription_item",
                        "current_period_end": int(period_end.timestamp()),
                    }
                ],
            },
        },
    )


def _plan(customer):
    customer.refresh_from_db()
    return (
        customer.kind,
        customer.source,
        customer.paid_until,
        customer.stripe_subscription_id,
    )


class TestYearlyPlan:
    @pytest.fixture(name="customer")
    def customer_fixture(self, sphere):
        return SpherePlan.objects.create(sphere=sphere, stripe_customer_id=CUSTOMER_ID)

    def test_completed_checkout_puts_the_sphere_on_the_yearly_plan(
        self, client, customer, stripe_api
    ):
        _stripe_says(stripe_api)

        response = _billing(
            client,
            "checkout.session.completed",
            {
                "id": "cs_plan",
                "object": "checkout.session",
                "mode": "subscription",
                "payment_status": "paid",
                "customer": CUSTOMER_ID,
                "subscription": "sub_1",
            },
        )

        assert_response(response, HTTPStatus.OK, json={"outcome": "subscribed"})
        assert _plan(customer) == (
            PlanKind.WHITE_GLOVE,
            PlanSource.STRIPE,
            PERIOD_END,
            "sub_1",
        )

    def test_renewal_moves_the_paid_date(self, client, customer, stripe_api):
        SpherePlan.objects.filter(pk=customer.pk).update(
            kind=PlanKind.WHITE_GLOVE,
            paid_until=PERIOD_END,
            stripe_subscription_id="sub_1",
        )
        next_year = PERIOD_END + timedelta(days=365)
        _stripe_says(stripe_api, period_end=next_year)

        response = _subscription_changed(client)

        assert_response(response, HTTPStatus.OK, json={"outcome": "renewed"})
        assert _plan(customer) == (
            PlanKind.WHITE_GLOVE,
            PlanSource.STRIPE,
            next_year,
            "sub_1",
        )

    def test_cancelled_subscription_returns_to_the_standard_plan(
        self, client, customer, stripe_api
    ):
        SpherePlan.objects.filter(pk=customer.pk).update(
            kind=PlanKind.WHITE_GLOVE,
            paid_until=PERIOD_END,
            stripe_subscription_id="sub_1",
        )
        _stripe_says(stripe_api, status="canceled")

        response = _subscription_changed(client)

        assert_response(response, HTTPStatus.OK, json={"outcome": "ended"})
        assert _plan(customer)[0] == PlanKind.STANDARD

    def test_late_event_for_a_live_subscription_still_records_what_stripe_says(
        self, client, customer, stripe_api
    ):
        # Stripe's answer, not the event's, decides: a "created" event that
        # arrives after the renewal writes the renewed date, not an older one.
        _stripe_says(stripe_api)

        response = _billing(
            client,
            "customer.subscription.created",
            {"id": "sub_1", "object": "subscription", "status": "incomplete"},
        )

        assert_response(response, HTTPStatus.OK, json={"outcome": "subscribed"})
        assert _plan(customer)[2] == PERIOD_END

    def test_buying_again_after_a_lapse_is_recorded_whatever_arrives_first(
        self, client, customer, stripe_api
    ):
        SpherePlan.objects.filter(pk=customer.pk).update(
            kind=PlanKind.STANDARD, stripe_subscription_id="sub_old"
        )
        _stripe_says(stripe_api, subscription_id="sub_new")

        response = _subscription_changed(client, "sub_new")

        assert_response(response, HTTPStatus.OK, json={"outcome": "subscribed"})
        assert _plan(customer) == (
            PlanKind.WHITE_GLOVE,
            PlanSource.STRIPE,
            PERIOD_END,
            "sub_new",
        )

    def test_an_older_subscription_ending_changes_nothing(
        self, client, customer, stripe_api
    ):
        SpherePlan.objects.filter(pk=customer.pk).update(
            kind=PlanKind.WHITE_GLOVE,
            paid_until=PERIOD_END,
            stripe_subscription_id="sub_new",
        )
        _stripe_says(stripe_api, subscription_id="sub_old", status="canceled")

        response = _subscription_changed(client, "sub_old")

        assert_response(response, HTTPStatus.OK, json={"outcome": "stale"})
        assert _plan(customer) == (
            PlanKind.WHITE_GLOVE,
            PlanSource.STRIPE,
            PERIOD_END,
            "sub_new",
        )

    def test_plan_recorded_by_hand_is_left_alone(self, client, customer, stripe_api):
        paid_until = datetime.now(UTC) + timedelta(days=200)
        SpherePlan.objects.filter(pk=customer.pk).update(
            kind=PlanKind.WHITE_GLOVE, source=PlanSource.MANUAL, paid_until=paid_until
        )
        _stripe_says(stripe_api, status="canceled")

        response = _subscription_changed(client)

        assert_response(response, HTTPStatus.OK, json={"outcome": "stale"})
        assert _plan(customer) == (
            PlanKind.WHITE_GLOVE,
            PlanSource.MANUAL,
            paid_until,
            "",
        )

    def test_unknown_customer_changes_nothing(self, client, customer, stripe_api):
        _stripe_says(stripe_api, customer="cus_stranger")

        response = _subscription_changed(client)

        assert_response(response, HTTPStatus.OK, json={"outcome": "not_ours"})
        assert _plan(customer)[0] == PlanKind.STANDARD

    def test_stripe_unreachable_asks_for_a_retry(self, client, customer, stripe_api):
        stripe_api.add(
            responses.GET,
            f"{API}/subscriptions/sub_1",
            status=HTTPStatus.INTERNAL_SERVER_ERROR,
            json={"error": {"message": "down", "type": "api_error"}},
        )

        response = _subscription_changed(client)

        assert_response(
            response,
            HTTPStatus.SERVICE_UNAVAILABLE,
            json={"error": "Stripe could not be reached; retry later."},
        )
        assert _plan(customer)[0] == PlanKind.STANDARD

    def test_one_off_invoice_is_not_the_yearly_plan(self, client, customer, stripe_api):
        response = _billing(
            client, "invoice.paid", {"id": "in_1", "customer": CUSTOMER_ID}
        )

        assert_response(response, HTTPStatus.OK, json={"outcome": "not_ours"})
        assert not stripe_api.calls
