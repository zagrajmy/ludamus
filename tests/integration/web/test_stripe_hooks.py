"""Stripe's webhooks, end to end: signature, idempotency, and what each changes.

How it could go wrong: a forged or replayed delivery is acted on; a redelivery
issues tickets twice; a paid order issues the wrong number of tickets or none;
a refund leaves tickets valid; an unpaid (delayed) checkout issues tickets; an
expiry kills a paid order; the order link is mailed twice, to nobody, not at
all, or says the tickets are there before the money is; a refused mail fails
the webhook Stripe then retries; a buyer's overlong address fails the payment
it came with; a deal paid by transfer is ended by a webhook, or a subscription
checkout is taken for a ticket order.
"""

import logging
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from smtplib import SMTPException
from urllib.parse import parse_qs

import pytest
import responses
from django.core.mail import EmailMessage
from django.urls import reverse

from ludamus.links.db.django.models import (
    PayoutAccount,
    SpherePlan,
    Ticket,
    TicketOrder,
)
from ludamus.pacts.billing import PlanSource
from ludamus.pacts.tickets import OrderStatus
from tests.integration.stripe_helpers import (
    ACCOUNT_ID,
    API,
    BILLING_SECRET,
    CONNECT_SECRET,
    GUEST_CLIENT,
    connected_account,
    event_payload,
    order,
    post_hook,
    ticket_type,
)
from tests.integration.utils import RequestTimeMatcher, assert_response

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


def _order_link(placed):
    path = reverse(
        "web:event:event-ticket-order",
        kwargs={"event_slug": placed.event.slug, "reference": placed.reference},
    )
    return f"https://testserver{path}"


def _buyer(email):
    return {"customer_details": {"email": email}}


PAID_LINE = "Thank you for your order. Your tickets and their QR codes are here:"
AWAITING_LINE = (
    "Thank you for your order. Your tickets appear on this page as soon as the"
    " payment reaches us:"
)
GUEST_LINES = [
    "Anyone with this link can see the tickets, so keep it to yourself.",
    (
        "To keep them in your Zagrajmy account, open the link and sign in or"
        " create an account there."
    ),
]


def _paragraphs(mail):
    return mail.body.split("\n\n")


class TestOrderMail:
    @pytest.fixture(name="guest_order")
    def guest_order_fixture(self, event):
        connected_account(event.sphere)
        return order(event, buyer=None, lines=[(ticket_type(event), 1)])

    def test_guest_gets_the_order_link_at_the_address_typed_into_checkout(
        self, client, guest_order, mailoutbox, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            response = _connect(
                client,
                "checkout.session.completed",
                _checkout(**_buyer("guest@example.com")),
            )

        assert_response(response, HTTPStatus.OK, json={"outcome": "paid"})
        assert TicketOrder.objects.get().email == "guest@example.com"
        assert [(mail.to, mail.subject, _paragraphs(mail)) for mail in mailoutbox] == [
            (
                ["guest@example.com"],
                f"Your tickets for {guest_order.event.name}",
                [PAID_LINE, _order_link(guest_order), *GUEST_LINES],
            )
        ]

    def test_redelivery_mails_nothing_more(
        self, client, guest_order, mailoutbox, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            _connect(
                client,
                "checkout.session.completed",
                _checkout(**_buyer("guest@example.com")),
            )
            response = _connect(
                client,
                "checkout.session.completed",
                _checkout(**_buyer("guest@example.com")),
            )

        assert_response(response, HTTPStatus.OK, json={"outcome": "stale"})
        assert len(mailoutbox) == 1

    def test_bank_transfer_is_mailed_when_checkout_completes_not_when_paid(
        self, client, guest_order, mailoutbox, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            _connect(
                client,
                "checkout.session.completed",
                _checkout(paid=False, **_buyer("guest@example.com")),
            )
            response = _connect(
                client,
                "checkout.session.async_payment_succeeded",
                _checkout(**_buyer("guest@example.com")),
                event_id="evt_2",
            )

        assert_response(response, HTTPStatus.OK, json={"outcome": "paid"})
        assert [(mail.to, _paragraphs(mail)) for mail in mailoutbox] == [
            (
                ["guest@example.com"],
                [AWAITING_LINE, _order_link(guest_order), *GUEST_LINES],
            )
        ]

    def test_success_that_beats_its_completion_mails_once(
        self, client, guest_order, mailoutbox, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            _connect(
                client,
                "checkout.session.async_payment_succeeded",
                _checkout(**_buyer("guest@example.com")),
            )
            response = _connect(
                client,
                "checkout.session.completed",
                _checkout(**_buyer("guest@example.com")),
                event_id="evt_2",
            )

        assert_response(response, HTTPStatus.OK, json={"outcome": "stale"})
        assert TicketOrder.objects.get(pk=guest_order.pk).status == OrderStatus.PAID
        assert [(mail.to, _paragraphs(mail)) for mail in mailoutbox] == [
            (["guest@example.com"], [PAID_LINE, _order_link(guest_order), *GUEST_LINES])
        ]

    def test_signed_in_buyer_gets_it_at_their_account_address(
        self,
        client,
        paid_setup,
        active_user,
        mailoutbox,
        django_capture_on_commit_callbacks,
    ):
        with django_capture_on_commit_callbacks(execute=True):
            _connect(client, "checkout.session.completed", _checkout())

        # The order is the account's already: no keep-it-secret, no sign-in.
        assert [(mail.to, _paragraphs(mail)) for mail in mailoutbox] == [
            ([active_user.email], [PAID_LINE, _order_link(paid_setup)])
        ]
        assert TicketOrder.objects.get(pk=paid_setup.pk).email == active_user.email

    def test_order_without_any_address_is_paid_and_mails_nothing(
        self, client, guest_order, mailoutbox, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            response = _connect(client, "checkout.session.completed", _checkout())

        assert_response(response, HTTPStatus.OK, json={"outcome": "paid"})
        assert not TicketOrder.objects.get(pk=guest_order.pk).email
        assert not mailoutbox

    def test_address_too_long_to_keep_is_dropped_and_the_payment_kept(
        self, client, guest_order, mailoutbox, django_capture_on_commit_callbacks
    ):
        # One past the 254 characters an EmailField holds.
        overlong = f"{'a' * 64}@{'b' * 63}.{'c' * 63}.{'d' * 54}.example"
        with django_capture_on_commit_callbacks(execute=True):
            response = _connect(
                client, "checkout.session.completed", _checkout(**_buyer(overlong))
            )

        assert_response(response, HTTPStatus.OK, json={"outcome": "paid"})
        paid = TicketOrder.objects.get(pk=guest_order.pk)
        assert (paid.status, paid.email) == (OrderStatus.PAID, "")
        assert Ticket.objects.filter(order=paid).count() == 1
        assert not mailoutbox

    def test_mail_server_refusing_does_not_fail_the_webhook(
        self,
        client,
        guest_order,
        monkeypatch,
        caplog,
        django_capture_on_commit_callbacks,
    ):
        def _refuse(*_args, **_kwargs):
            raise SMTPException

        monkeypatch.setattr(EmailMessage, "send", _refuse)

        with (
            caplog.at_level(logging.INFO, logger="ludamus.links.db.django.tickets"),
            django_capture_on_commit_callbacks(execute=True),
        ):
            response = _connect(
                client,
                "checkout.session.completed",
                _checkout(**_buyer("guest@example.com")),
            )

        assert_response(response, HTTPStatus.OK, json={"outcome": "paid"})
        assert TicketOrder.objects.get(pk=guest_order.pk).status == OrderStatus.PAID
        assert [
            (record.levelno, record.getMessage())
            for record in caplog.records
            if record.getMessage().startswith("Ticket order mail")
        ] == [(logging.ERROR, f"Ticket order mail failed: order={guest_order.pk}")]

    def test_payment_for_an_abandoned_order_mails_nothing(
        self,
        client,
        guest_order,
        stripe_api,
        mailoutbox,
        django_capture_on_commit_callbacks,
    ):
        TicketOrder.objects.filter(pk=guest_order.pk).update(status=OrderStatus.EXPIRED)
        stripe_api.add(
            responses.POST, f"{API}/refunds", json={"id": "re_1", "object": "refund"}
        )

        with django_capture_on_commit_callbacks(execute=True):
            response = _connect(
                client,
                "checkout.session.completed",
                _checkout(**_buyer("guest@example.com")),
            )

        assert_response(response, HTTPStatus.OK, json={"outcome": "refunded"})
        assert not mailoutbox


class TestGuestNetwork:
    # A guest's keyed network limits how many orders it holds at once; an
    # order that holds no seats any more has no reason to keep it.
    @pytest.fixture(name="guest_order")
    def guest_order_fixture(self, event):
        connected_account(event.sphere)
        return order(
            event,
            buyer=None,
            lines=[(ticket_type(event), 1)],
            guest_client=GUEST_CLIENT,
        )

    @pytest.mark.parametrize(
        ("event_type", "paid", "outcome", "kept"),
        (
            pytest.param("checkout.session.completed", True, "paid", "", id="paid"),
            pytest.param(
                "checkout.session.completed",
                False,
                "awaiting_payment",
                GUEST_CLIENT,
                id="awaiting-transfer",
            ),
            pytest.param(
                "checkout.session.expired", False, "expired", "", id="expired"
            ),
            pytest.param(
                "checkout.session.async_payment_failed",
                False,
                "failed",
                "",
                id="failed",
            ),
        ),
    )
    def test_is_kept_only_while_the_order_holds_seats(
        self, client, guest_order, *, event_type, paid, outcome, kept
    ):
        response = _connect(client, event_type, _checkout(paid=paid))

        assert_response(response, HTTPStatus.OK, json={"outcome": outcome})
        assert TicketOrder.objects.get(pk=guest_order.pk).guest_client == kept

    def test_transfer_that_arrives_forgets_it(self, client, guest_order):
        _connect(client, "checkout.session.completed", _checkout(paid=False))

        response = _connect(
            client,
            "checkout.session.async_payment_succeeded",
            _checkout(),
            event_id="evt_2",
        )

        assert_response(response, HTTPStatus.OK, json={"outcome": "paid"})
        assert not TicketOrder.objects.get(pk=guest_order.pk).guest_client


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

    def test_partial_refund_leaves_the_order_alone(self, client, paid_setup):
        _connect(client, "checkout.session.completed", _checkout())

        response = _connect(
            client,
            "charge.refunded",
            {"id": "ch_1", "payment_intent": "pi_test_1", "refunded": False},
            event_id="evt_2",
        )

        assert_response(response, HTTPStatus.OK, json={"outcome": "partly_refunded"})
        assert TicketOrder.objects.get(pk=paid_setup.pk).status == OrderStatus.PAID

    def test_refund_of_a_charge_without_a_payment_intent_is_not_ours(
        self, client, paid_setup
    ):
        # NOTE: the organizer's own Stripe account can refund charges it made
        # outside Zagrajmy, through the older Charges API.
        _connect(client, "checkout.session.completed", _checkout())

        response = _connect(
            client,
            "charge.refunded",
            {"id": "ch_legacy", "payment_intent": None, "refunded": True},
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


def _subscription_changed(client, subscription_id="sub_1", *, customer=CUSTOMER_ID):
    return _billing(
        client,
        "customer.subscription.updated",
        {
            "id": subscription_id,
            "object": "subscription",
            "customer": customer,
            "status": "whatever",
        },
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
                "data": (
                    []
                    if period_end is None
                    else [
                        {
                            "id": "si_1",
                            "object": "subscription_item",
                            "current_period_end": int(period_end.timestamp()),
                        }
                    ]
                ),
            },
        },
    )


def _deal(plan):
    plan.refresh_from_db()
    return (plan.source, plan.paid_until, plan.stripe_subscription_id)


class TestDealSync:
    @pytest.fixture(name="deal")
    def deal_fixture(self, sphere):
        return SpherePlan.objects.create(
            sphere=sphere,
            technical_partner=True,
            yearly_price=500_000,
            source=PlanSource.STRIPE,
            stripe_customer_id=CUSTOMER_ID,
        )

    def test_first_subscription_records_what_it_is_paid_until(
        self, client, deal, stripe_api
    ):
        _stripe_says(stripe_api)

        response = _subscription_changed(client)

        assert_response(response, HTTPStatus.OK, json={"outcome": "subscribed"})
        assert _deal(deal) == (PlanSource.STRIPE, PERIOD_END, "sub_1")

    def test_renewal_moves_the_paid_date(self, client, deal, stripe_api):
        SpherePlan.objects.filter(pk=deal.pk).update(
            paid_until=PERIOD_END, stripe_subscription_id="sub_1"
        )
        next_year = PERIOD_END + timedelta(days=365)
        _stripe_says(stripe_api, period_end=next_year)

        response = _subscription_changed(client)

        assert_response(response, HTTPStatus.OK, json={"outcome": "renewed"})
        assert _deal(deal) == (PlanSource.STRIPE, next_year, "sub_1")

    def test_live_subscription_without_a_period_keeps_the_date_on_record(
        self, client, deal, stripe_api
    ):
        SpherePlan.objects.filter(pk=deal.pk).update(
            paid_until=PERIOD_END, stripe_subscription_id="sub_1"
        )
        _stripe_says(stripe_api, period_end=None)

        response = _subscription_changed(client)

        assert_response(response, HTTPStatus.OK, json={"outcome": "renewed"})
        assert _deal(deal) == (PlanSource.STRIPE, PERIOD_END, "sub_1")

    def test_cancelled_subscription_ends_the_deal_now(self, client, deal, stripe_api):
        SpherePlan.objects.filter(pk=deal.pk).update(
            paid_until=PERIOD_END, stripe_subscription_id="sub_1"
        )
        _stripe_says(stripe_api, status="canceled")

        response = _subscription_changed(client)

        assert_response(response, HTTPStatus.OK, json={"outcome": "ended"})
        assert _deal(deal) == (PlanSource.STRIPE, RequestTimeMatcher(), "sub_1")

    def test_subscription_that_ran_out_ends_the_deal_when_its_period_did(
        self, client, deal, stripe_api
    ):
        ran_out = datetime.now(UTC) - timedelta(days=3)
        SpherePlan.objects.filter(pk=deal.pk).update(
            paid_until=PERIOD_END, stripe_subscription_id="sub_1"
        )
        _stripe_says(stripe_api, status="unpaid", period_end=ran_out)

        response = _subscription_changed(client)

        assert_response(response, HTTPStatus.OK, json={"outcome": "ended"})
        assert _deal(deal)[1] == ran_out.replace(microsecond=0)

    def test_late_event_for_a_live_subscription_still_records_what_stripe_says(
        self, client, deal, stripe_api
    ):
        # Stripe's answer, not the event's, decides: a "created" event that
        # arrives after the renewal writes the renewed date, not an older one.
        _stripe_says(stripe_api)

        response = _billing(
            client,
            "customer.subscription.created",
            {
                "id": "sub_1",
                "object": "subscription",
                "customer": CUSTOMER_ID,
                "status": "incomplete",
            },
        )

        assert_response(response, HTTPStatus.OK, json={"outcome": "subscribed"})
        assert _deal(deal)[1] == PERIOD_END

    def test_new_subscription_after_a_lapse_takes_over(self, client, deal, stripe_api):
        lapsed = datetime(2026, 1, 1, tzinfo=UTC)
        SpherePlan.objects.filter(pk=deal.pk).update(
            paid_until=lapsed, stripe_subscription_id="sub_old"
        )
        _stripe_says(stripe_api, subscription_id="sub_new")

        response = _subscription_changed(client, "sub_new")

        assert_response(response, HTTPStatus.OK, json={"outcome": "subscribed"})
        assert _deal(deal) == (PlanSource.STRIPE, PERIOD_END, "sub_new")

    def test_an_older_subscription_ending_changes_nothing(
        self, client, deal, stripe_api
    ):
        SpherePlan.objects.filter(pk=deal.pk).update(
            paid_until=PERIOD_END, stripe_subscription_id="sub_new"
        )
        _stripe_says(stripe_api, subscription_id="sub_old", status="canceled")

        response = _subscription_changed(client, "sub_old")

        assert_response(response, HTTPStatus.OK, json={"outcome": "stale"})
        assert _deal(deal) == (PlanSource.STRIPE, PERIOD_END, "sub_new")

    def test_deal_paid_by_transfer_is_left_alone(self, client, deal, stripe_api):
        paid_until = datetime.now(UTC) + timedelta(days=200)
        SpherePlan.objects.filter(pk=deal.pk).update(
            source=PlanSource.MANUAL, paid_until=paid_until
        )
        _stripe_says(stripe_api, status="canceled")

        response = _subscription_changed(client)

        assert_response(response, HTTPStatus.OK, json={"outcome": "stale"})
        assert _deal(deal) == (PlanSource.MANUAL, paid_until, "")
        assert not stripe_api.calls

    def test_unknown_customer_changes_nothing(self, client, deal, stripe_api):
        _stripe_says(stripe_api, customer="cus_stranger")

        response = _subscription_changed(client, customer="cus_stranger")

        assert_response(response, HTTPStatus.OK, json={"outcome": "not_ours"})
        assert _deal(deal) == (PlanSource.STRIPE, None, "")

    def test_stripe_unreachable_asks_for_a_retry(self, client, deal, stripe_api):
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
        assert _deal(deal) == (PlanSource.STRIPE, None, "")

    def test_subscription_checkout_is_left_to_the_subscription_events(
        self, client, deal, stripe_api
    ):
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

        assert_response(response, HTTPStatus.OK, json={"outcome": "not_ours"})
        assert _deal(deal) == (PlanSource.STRIPE, None, "")
        assert not stripe_api.calls

    def test_one_off_invoice_changes_nothing(self, client, deal, stripe_api):
        response = _billing(
            client, "invoice.paid", {"id": "in_1", "customer": CUSTOMER_ID}
        )

        assert_response(response, HTTPStatus.OK, json={"outcome": "not_ours"})
        assert not stripe_api.calls
