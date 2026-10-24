"""Buying tickets: the ticket page and the hand-off to Stripe Checkout.

How it could go wrong: a free event grows a ticket page; a script holds a
sell-out through guest checkouts, from one address or across an IPv6 /64;
the guest limit binds an account, another network or another event; a ticket
type id from another event is sold; seats held by someone still in Checkout
are sold twice; Zagrajmy's fee (or a deal's lower one) or the connected
account is wrong on the Checkout Session; a Stripe failure keeps seats held.
"""

import json
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from itertools import count
from urllib.parse import parse_qs

import pytest
import responses
from django.contrib import messages
from django.test import Client
from django.urls import reverse

from ludamus.links.db.django.models import SpherePlan, Ticket, TicketOrder
from ludamus.pacts import EventDTO
from ludamus.pacts.billing import PlanSource
from ludamus.pacts.tickets import (
    MAX_TICKETS_PER_ORDER,
    EventShopDTO,
    OfferState,
    OrderStatus,
    TicketOfferDTO,
    TicketTypeDTO,
)
from ludamus.specs.tickets import GUEST_HOLDS_PER_CLIENT
from tests.integration.conftest import EventFactory, UserFactory
from tests.integration.stripe_helpers import (
    ACCOUNT_ID,
    API,
    cancel_url,
    connected_account,
    order,
    order_url,
    ticket_type,
    tickets_url,
)
from tests.integration.utils import assert_response, assert_response_404

pytestmark = pytest.mark.usefixtures("stripe_settings")

CHECKOUT_URL = "https://checkout.stripe.com/c/pay/cs_test_new"
TOO_MANY_HOLDS = (
    messages.ERROR,
    (
        "Your connection already has unpaid orders for this event. Finish or"
        " cancel one, or sign in to buy now."
    ),
)


def _buy_url(event):
    return reverse("web:event:event-tickets-buy", kwargs={"event_slug": event.slug})


def _type_dto(kind, *, sold=0, held=0):
    return TicketTypeDTO(
        pk=kind.pk,
        event_id=kind.event_id,
        name=kind.name,
        description=kind.description,
        price=kind.price,
        currency=kind.currency,
        quantity=kind.quantity,
        sales_start=kind.sales_start,
        sales_end=kind.sales_end,
        is_archived=kind.is_archived,
        order=kind.order,
        sold=sold,
        held=held,
    )


def _mock_checkout(stripe_api, *, status=HTTPStatus.OK):
    stripe_api.add(
        responses.POST,
        f"{API}/checkout/sessions",
        json=(
            {"id": "cs_test_new", "object": "checkout.session", "url": CHECKOUT_URL}
            if status == HTTPStatus.OK
            else {"error": {"type": "api_error", "message": "Stripe is down"}}
        ),
        status=status,
    )


def _mock_checkouts(stripe_api):
    # A Checkout Session id per call: the order table holds each one once.
    numbers = count()

    def _session(_request):
        session_id = f"cs_test_{next(numbers)}"
        return (
            HTTPStatus.OK,
            {"Content-Type": "application/json"},
            json.dumps(
                {"id": session_id, "object": "checkout.session", "url": CHECKOUT_URL}
            ),
        )

    stripe_api.add_callback(
        responses.POST, f"{API}/checkout/sessions", callback=_session
    )


def _sent(stripe_api):
    return parse_qs(stripe_api.calls[0].request.body)


class TestEventTicketsPageView:
    def test_free_event_has_no_ticket_page(self, client, event):
        response = client.get(tickets_url(event))

        assert_response_404(response)

    def test_lists_what_is_on_sale_and_what_is_left(self, client, event, active_user):
        connected_account(event.sphere)
        capped = ticket_type(event, quantity=5)
        archived = ticket_type(event, name="Old", is_archived=True)
        # Someone is still paying for two: they are not for sale right now.
        order(event, buyer=active_user, lines=[(capped, 2)])
        order(event, buyer=active_user, lines=[(archived, 1)], session_id="cs_2")

        response = client.get(tickets_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/tickets.html",
            context_data={
                "event": EventDTO.model_validate(event),
                "shop": EventShopDTO(
                    offers=[
                        TicketOfferDTO(
                            ticket_type=_type_dto(capped, held=2),
                            state=OfferState.ON_SALE,
                            remaining=3,
                            few_left=True,
                            max_quantity=3,
                        )
                    ],
                    accepting_payments=True,
                    viewer_ticket_count=0,
                ),
                "max_per_order": MAX_TICKETS_PER_ORDER,
            },
        )

    def test_event_page_keeps_a_holders_count_once_sales_are_over(
        self, authenticated_client, event, active_user
    ):
        kind = ticket_type(event, is_archived=True)
        paid = order(event, buyer=active_user, lines=[(kind, 1)], status="paid")
        Ticket.objects.create(
            order=paid, ticket_type=kind, holder=active_user, code="AAAAAAAA55"
        )

        response = authenticated_client.get(
            reverse("web:chronology:event", kwargs={"slug": event.slug})
        )

        shop = response.context_data["ticket_shop"]
        assert (shop.has_tickets, shop.viewer_ticket_count) == (False, 1)

    def test_signed_in_buyer_sees_how_many_valid_tickets_they_hold(
        self, authenticated_client, event, active_user
    ):
        connected_account(event.sphere)
        kind = ticket_type(event)
        paid = order(event, buyer=active_user, lines=[(kind, 2)], status="paid")
        Ticket.objects.create(
            order=paid, ticket_type=kind, holder=active_user, code="AAAAAAAA22"
        )
        Ticket.objects.create(
            order=paid, ticket_type=kind, holder=active_user, code="AAAAAAAA33"
        )
        refunded = order(
            event,
            buyer=active_user,
            lines=[(kind, 1)],
            status="refunded",
            session_id="cs_2",
        )
        Ticket.objects.create(
            order=refunded, ticket_type=kind, holder=active_user, code="AAAAAAAA44"
        )

        response = authenticated_client.get(tickets_url(event))

        shop = response.context_data["shop"]
        assert shop.viewer_ticket_count == 1 + 1

    def test_unpublished_event_stays_hidden(self, client, sphere):
        hidden = EventFactory(sphere=sphere, publication_time=None)
        ticket_type(hidden)

        response = client.get(tickets_url(hidden))

        assert_response_404(response)


class TestEventTicketsBuyActionView:
    def test_guest_starts_checkout_and_stripe_asks_for_the_email(
        self, client, event, stripe_api
    ):
        connected_account(event.sphere)
        kind = ticket_type(event)
        _mock_checkout(stripe_api)

        response = client.post(_buy_url(event), {f"quantity-{kind.pk}": "1"})

        assert_response(response, HTTPStatus.FOUND, url=CHECKOUT_URL)
        created = TicketOrder.objects.get()
        assert (created.buyer_id, created.email, created.status) == (
            None,
            "",
            OrderStatus.PENDING,
        )
        sent = _sent(stripe_api)
        assert "customer_email" not in sent
        assert sent["success_url"] == [f"http://testserver{order_url(event, created)}"]

    def test_buyer_without_an_email_is_asked_for_one_by_checkout(
        self, authenticated_client, event, active_user, stripe_api
    ):
        connected_account(event.sphere)
        kind = ticket_type(event)
        active_user.email = ""
        active_user.save()
        _mock_checkout(stripe_api)

        response = authenticated_client.post(
            _buy_url(event), {f"quantity-{kind.pk}": "1"}
        )

        assert_response(response, HTTPStatus.FOUND, url=CHECKOUT_URL)
        created = TicketOrder.objects.get()
        assert (created.buyer_id, created.email) == (active_user.pk, "")
        assert "customer_email" not in _sent(stripe_api)

    def test_order_over_the_limit_across_types_starts_nothing(
        self, authenticated_client, event, stripe_api
    ):
        connected_account(event.sphere)
        weekend = ticket_type(event)
        saturday = ticket_type(event, name="Saturday", price=3000)

        response = authenticated_client.post(
            _buy_url(event),
            {
                f"quantity-{weekend.pk}": str(MAX_TICKETS_PER_ORDER),
                f"quantity-{saturday.pk}": "1",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=tickets_url(event),
            messages=[
                (
                    messages.ERROR,
                    f"You can buy up to {MAX_TICKETS_PER_ORDER} tickets in one order.",
                )
            ],
        )
        assert not TicketOrder.objects.exists()
        assert not stripe_api.calls

    def test_starts_checkout_on_the_spheres_account_with_the_fee(
        self, authenticated_client, event, active_user, stripe_api
    ):
        connected_account(event.sphere)
        kind = ticket_type(event, price=5000)
        _mock_checkout(stripe_api)

        response = authenticated_client.post(
            _buy_url(event), {f"quantity-{kind.pk}": "2"}
        )

        assert_response(response, HTTPStatus.FOUND, url=CHECKOUT_URL)
        created = TicketOrder.objects.get()
        assert (
            created.status,
            created.buyer_id,
            created.email,
            created.total,
            created.platform_fee,
            created.stripe_checkout_session_id,
        ) == (
            OrderStatus.PENDING,
            active_user.pk,
            active_user.email,
            10_000,
            350,
            "cs_test_new",
        )
        request = stripe_api.calls[0].request
        assert request.headers["Stripe-Account"] == ACCOUNT_ID
        sent = parse_qs(request.body)
        assert sent["payment_intent_data[application_fee_amount]"] == ["350"]
        assert sent["customer_email"] == [active_user.email]
        assert sent["line_items[0][quantity]"] == ["2"]
        assert sent["line_items[0][price_data][unit_amount]"] == ["5000"]
        assert sent["expires_at"] == [str(int(created.hold_until.timestamp()))]
        assert sent["success_url"] == [f"http://testserver{order_url(event, created)}"]
        assert sent["cancel_url"] == [f"http://testserver{cancel_url(event, created)}"]

    @pytest.mark.parametrize(
        ("deal", "fee"),
        (
            pytest.param({"ticket_fee_bps": 100}, 100, id="lower-fee-deal"),
            pytest.param(
                {"technical_partner": True}, 350, id="deal-without-a-fee-term"
            ),
            pytest.param(
                {
                    "ticket_fee_bps": 0,
                    "paid_until": datetime.now(UTC) - timedelta(days=1),
                },
                350,
                id="lapsed-deal",
            ),
            pytest.param(
                {
                    "ticket_fee_bps": 0,
                    "source": PlanSource.STRIPE,
                    "stripe_customer_id": "cus_new",
                },
                350,
                id="stripe-deal-before-its-first-invoice",
            ),
        ),
    )
    def test_the_spheres_deal_sets_zagrajmys_fee(
        self, authenticated_client, event, stripe_api, deal, fee
    ):
        SpherePlan.objects.create(sphere=event.sphere, **deal)
        connected_account(event.sphere)
        kind = ticket_type(event, price=5000)
        _mock_checkout(stripe_api)

        response = authenticated_client.post(
            _buy_url(event), {f"quantity-{kind.pk}": "2"}
        )

        assert_response(response, HTTPStatus.FOUND, url=CHECKOUT_URL)
        assert TicketOrder.objects.get().platform_fee == fee
        assert _sent(stripe_api)["payment_intent_data[application_fee_amount]"] == [
            str(fee)
        ]

    def test_fee_free_deal_sends_stripe_no_application_fee(
        self, authenticated_client, event, stripe_api
    ):
        SpherePlan.objects.create(sphere=event.sphere, ticket_fee_bps=0)
        connected_account(event.sphere)
        kind = ticket_type(event, price=5000)
        _mock_checkout(stripe_api)

        response = authenticated_client.post(
            _buy_url(event), {f"quantity-{kind.pk}": "2"}
        )

        assert_response(response, HTTPStatus.FOUND, url=CHECKOUT_URL)
        assert TicketOrder.objects.get().platform_fee == 0
        assert "payment_intent_data[application_fee_amount]" not in _sent(stripe_api)

    def test_type_from_another_event_is_not_sold(
        self, authenticated_client, event, stripe_api
    ):
        connected_account(event.sphere)
        ticket_type(event)
        elsewhere = ticket_type(EventFactory(sphere=event.sphere))

        response = authenticated_client.post(
            _buy_url(event), {f"quantity-{elsewhere.pk}": "1"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=tickets_url(event),
            messages=[(messages.ERROR, "That ticket isn't on sale right now.")],
        )
        assert not TicketOrder.objects.exists()
        assert not stripe_api.calls

    def test_seats_held_in_checkout_are_not_sold_twice(
        self, authenticated_client, event, stripe_api
    ):
        connected_account(event.sphere)
        kind = ticket_type(event, quantity=2)
        order(event, buyer=UserFactory(), lines=[(kind, 2)])

        response = authenticated_client.post(
            _buy_url(event), {f"quantity-{kind.pk}": "1"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=tickets_url(event),
            messages=[
                (
                    messages.ERROR,
                    "Not enough tickets left. Pick fewer, or another ticket type.",
                )
            ],
        )
        assert TicketOrder.objects.count() == 1
        assert not stripe_api.calls

    def test_seats_stay_held_while_a_late_webhook_may_still_pay(
        self, authenticated_client, event, stripe_api
    ):
        # The other buyer may have paid at the last minute of their hold;
        # Stripe's word on it can arrive after the hold ends.
        connected_account(event.sphere)
        kind = ticket_type(event, quantity=2)
        order(event, buyer=UserFactory(), lines=[(kind, 2)], hold_minutes=-1)

        response = authenticated_client.post(
            _buy_url(event), {f"quantity-{kind.pk}": "1"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=tickets_url(event),
            messages=[
                (
                    messages.ERROR,
                    "Not enough tickets left. Pick fewer, or another ticket type.",
                )
            ],
        )
        assert not stripe_api.calls

    def test_hold_long_past_its_grace_frees_its_seats(
        self, authenticated_client, event, stripe_api
    ):
        connected_account(event.sphere)
        kind = ticket_type(event, quantity=2)
        order(event, buyer=UserFactory(), lines=[(kind, 2)], hold_minutes=-61)
        _mock_checkout(stripe_api)

        response = authenticated_client.post(
            _buy_url(event), {f"quantity-{kind.pk}": "2"}
        )

        assert_response(response, HTTPStatus.FOUND, url=CHECKOUT_URL)

    def test_stripe_failure_releases_the_seats(
        self, authenticated_client, event, stripe_api
    ):
        connected_account(event.sphere)
        kind = ticket_type(event, quantity=1)
        _mock_checkout(stripe_api, status=HTTPStatus.BAD_REQUEST)

        response = authenticated_client.post(
            _buy_url(event), {f"quantity-{kind.pk}": "1"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=tickets_url(event),
            messages=[
                (
                    messages.ERROR,
                    (
                        "We couldn't reach the payment provider. Nothing was"
                        " charged; try again in a moment."
                    ),
                )
            ],
        )
        assert TicketOrder.objects.get().status == OrderStatus.FAILED

    def test_sales_wait_for_a_connected_account(
        self, authenticated_client, event, stripe_api
    ):
        connected_account(event.sphere, charges_enabled=False)
        kind = ticket_type(event)

        response = authenticated_client.post(
            _buy_url(event), {f"quantity-{kind.pk}": "1"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=tickets_url(event),
            messages=[
                (
                    messages.ERROR,
                    "Ticket sales for this event are paused. Try again later.",
                )
            ],
        )
        assert not TicketOrder.objects.exists()
        assert not stripe_api.calls

    @pytest.mark.parametrize("quantity", ("0", "", "-1", "abc", "\u0661", "9" * 5000))
    def test_unusable_quantity_starts_nothing(
        self, authenticated_client, event, stripe_api, quantity
    ):
        connected_account(event.sphere)
        kind = ticket_type(event)

        response = authenticated_client.post(
            _buy_url(event), {f"quantity-{kind.pk}": quantity}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=tickets_url(event),
            messages=[(messages.ERROR, "Choose how many tickets you want.")],
        )
        assert not TicketOrder.objects.exists()


def _guest_buys(guest, event, kind, **meta):
    return guest.post(_buy_url(event), {f"quantity-{kind.pk}": "1"}, **meta)


class TestGuestHoldLimit:
    @pytest.fixture(name="kind")
    def kind_fixture(self, event, stripe_api):
        connected_account(event.sphere)
        _mock_checkouts(stripe_api)
        return ticket_type(event)

    def _hold_the_limit(self, guest, event, kind, **meta):
        for _ in range(GUEST_HOLDS_PER_CLIENT):
            _guest_buys(guest, event, kind, **meta)

    def test_network_holding_its_share_starts_nothing(
        self, client, event, kind, stripe_api
    ):
        self._hold_the_limit(client, event, kind)

        response = _guest_buys(client, event, kind)

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=tickets_url(event),
            messages=[TOO_MANY_HOLDS],
        )
        assert TicketOrder.objects.count() == GUEST_HOLDS_PER_CLIENT
        assert len(stripe_api.calls) == GUEST_HOLDS_PER_CLIENT

    @pytest.mark.parametrize(
        ("status", "hold_minutes"),
        (
            pytest.param(OrderStatus.AWAITING_PAYMENT, 30, id="awaiting-transfer"),
            # Stripe's word on a last-minute payment may still be on its way.
            pytest.param(OrderStatus.PENDING, -59, id="hold-within-webhook-grace"),
        ),
    )
    def test_order_still_holding_seats_keeps_its_place(
        self, client, event, kind, *, status, hold_minutes
    ):
        self._hold_the_limit(client, event, kind)
        TicketOrder.objects.filter(pk=TicketOrder.objects.earliest("pk").pk).update(
            status=status,
            hold_until=datetime.now(UTC) + timedelta(minutes=hold_minutes),
        )

        response = _guest_buys(client, event, kind)

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=tickets_url(event),
            messages=[TOO_MANY_HOLDS],
        )

    @pytest.mark.parametrize(
        ("status", "hold_minutes"),
        (
            pytest.param(OrderStatus.PENDING, -61, id="hold-past-webhook-grace"),
            pytest.param(OrderStatus.EXPIRED, 30, id="expired"),
            pytest.param(OrderStatus.FAILED, 30, id="failed"),
            pytest.param(OrderStatus.PAID, 30, id="paid"),
        ),
    )
    def test_order_that_holds_nothing_unpaid_frees_its_place(
        self, client, event, kind, *, status, hold_minutes
    ):
        self._hold_the_limit(client, event, kind)
        TicketOrder.objects.filter(pk=TicketOrder.objects.earliest("pk").pk).update(
            status=status,
            hold_until=datetime.now(UTC) + timedelta(minutes=hold_minutes),
        )

        response = _guest_buys(client, event, kind)

        assert_response(response, HTTPStatus.FOUND, url=CHECKOUT_URL)

    def test_one_ipv6_network_counts_as_one_client(self, client, event, kind):
        for host in range(GUEST_HOLDS_PER_CLIENT):
            _guest_buys(client, event, kind, REMOTE_ADDR=f"2001:db8:1:2::{host + 1}")

        response = _guest_buys(client, event, kind, REMOTE_ADDR="2001:db8:1:2:ff::9")

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=tickets_url(event),
            messages=[TOO_MANY_HOLDS],
        )

    def test_neighbouring_ipv6_network_is_another_client(self, client, event, kind):
        for host in range(GUEST_HOLDS_PER_CLIENT):
            _guest_buys(client, event, kind, REMOTE_ADDR=f"2001:db8:1:2::{host + 1}")

        response = _guest_buys(client, event, kind, REMOTE_ADDR="2001:db8:1:3::1")

        assert_response(response, HTTPStatus.FOUND, url=CHECKOUT_URL)

    def test_client_is_told_apart_by_the_address_cloudflare_saw(
        self, client, event, kind
    ):
        # Every request reaches the origin from a Cloudflare address.
        self._hold_the_limit(client, event, kind, HTTP_CF_CONNECTING_IP="198.51.100.1")

        response = _guest_buys(
            client, event, kind, HTTP_CF_CONNECTING_IP="198.51.100.2"
        )

        assert_response(response, HTTPStatus.FOUND, url=CHECKOUT_URL)

    def test_another_event_is_not_held_to_it(self, client, event, kind):
        self._hold_the_limit(client, event, kind)
        elsewhere = EventFactory(sphere=event.sphere)

        response = _guest_buys(client, elsewhere, ticket_type(elsewhere))

        assert_response(response, HTTPStatus.FOUND, url=CHECKOUT_URL)

    def test_account_is_never_held_to_it(self, authenticated_client, event, kind):
        self._hold_the_limit(Client(), event, kind)
        for _ in range(GUEST_HOLDS_PER_CLIENT):
            _guest_buys(authenticated_client, event, kind)

        response = _guest_buys(authenticated_client, event, kind)

        assert_response(response, HTTPStatus.FOUND, url=CHECKOUT_URL)
        assert TicketOrder.objects.filter(buyer__isnull=False).count() == (
            GUEST_HOLDS_PER_CLIENT + 1
        )
        assert (
            not TicketOrder.objects.filter(buyer__isnull=False)
            .exclude(guest_client="")
            .exists()
        )
