"""Buying tickets: the page, Checkout hand-off, the order page, and cancelling.

How it could go wrong: a free event grows a ticket page; a signed-out visitor
starts a checkout; a ticket type id from another event is sold; seats held by
someone still in Checkout are sold twice; Zagrajmy's fee or the connected
account is wrong on the Checkout Session; a Stripe failure keeps seats held;
someone else's order is shown or cancelled.
"""

from http import HTTPStatus
from urllib.parse import parse_qs, urlencode

import pytest
import responses
from django.contrib import messages
from django.core.signing import Signer
from django.urls import reverse

from ludamus.links.db.django.models import TicketOrder
from ludamus.pacts import EventDTO
from ludamus.pacts.tickets import (
    MAX_TICKETS_PER_ORDER,
    EventShopDTO,
    OfferState,
    OrderStatus,
    TicketOfferDTO,
    TicketTypeDTO,
)
from tests.integration.conftest import EventFactory, UserFactory
from tests.integration.stripe_helpers import (
    ACCOUNT_ID,
    API,
    connected_account,
    order,
    ticket_type,
)
from tests.integration.utils import assert_response, assert_response_404

pytestmark = pytest.mark.usefixtures("stripe_settings")

CHECKOUT_URL = "https://checkout.stripe.com/c/pay/cs_test_new"


def _tickets_url(event):
    return reverse("web:event:event-tickets", kwargs={"event_slug": event.slug})


def _buy_url(event):
    return reverse("web:event:event-tickets-buy", kwargs={"event_slug": event.slug})


def _order_url(event, pk):
    return reverse(
        "web:event:event-ticket-order", kwargs={"event_slug": event.slug, "pk": pk}
    )


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


class TestEventTicketsPageView:
    def test_free_event_has_no_ticket_page(self, client, event):
        response = client.get(_tickets_url(event))

        assert_response_404(response)

    def test_lists_what_is_on_sale_and_what_is_left(self, client, event, active_user):
        connected_account(event.sphere)
        capped = ticket_type(event, quantity=5)
        archived = ticket_type(event, name="Old", is_archived=True)
        # Someone is still paying for two: they are not for sale right now.
        order(event, buyer=active_user, lines=[(capped, 2)])
        order(event, buyer=active_user, lines=[(archived, 1)], session_id="cs_2")

        response = client.get(_tickets_url(event))

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

    def test_unpublished_event_stays_hidden(self, client, sphere):
        hidden = EventFactory(sphere=sphere, publication_time=None)
        ticket_type(hidden)

        response = client.get(_tickets_url(hidden))

        assert_response_404(response)


class TestEventTicketsBuyActionView:
    def test_signed_out_visitor_is_sent_to_log_in(self, client, event):
        connected_account(event.sphere)
        kind = ticket_type(event)

        response = client.post(_buy_url(event), {f"quantity-{kind.pk}": "1"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=f"/crowd/login-required/?next={_tickets_url(event)}",
        )
        assert not TicketOrder.objects.exists()

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
            created.total,
            created.platform_fee,
            created.stripe_checkout_session_id,
        ) == (OrderStatus.PENDING, active_user.pk, 10_000, 350, "cs_test_new")
        request = stripe_api.calls[0].request
        assert request.headers["Stripe-Account"] == ACCOUNT_ID
        sent = parse_qs(request.body)
        assert sent["payment_intent_data[application_fee_amount]"] == ["350"]
        assert sent["line_items[0][quantity]"] == ["2"]
        assert sent["line_items[0][price_data][unit_amount]"] == ["5000"]
        assert sent["expires_at"] == [str(int(created.hold_until.timestamp()))]
        assert sent["success_url"] == [
            f"http://testserver{_order_url(event, created.pk)}"
        ]
        assert sent["cancel_url"] == [
            f"http://testserver{_cancel_url(event, created.pk)}"
        ]

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
            url=_tickets_url(event),
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
            url=_tickets_url(event),
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
            url=_tickets_url(event),
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
            url=_tickets_url(event),
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
            url=_tickets_url(event),
            messages=[
                (
                    messages.ERROR,
                    "Ticket sales for this event are paused. Try again later.",
                )
            ],
        )
        assert not TicketOrder.objects.exists()

    @pytest.mark.parametrize("quantity", ("0", "", "-1", "abc", "11"))
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
            url=_tickets_url(event),
            messages=[(messages.ERROR, "Choose how many tickets you want.")],
        )
        assert not TicketOrder.objects.exists()


_SIGNER = Signer(salt="ticket-checkout-cancel")


def _cancel_url(event, pk, *, token=None):
    path = reverse(
        "web:event:event-ticket-order-cancel",
        kwargs={"event_slug": event.slug, "pk": pk},
    )
    return f"{path}?{urlencode({'token': token or _SIGNER.sign(str(pk))})}"


class TestEventTicketOrderPages:
    def test_someone_elses_order_is_not_found(self, authenticated_client, event):
        kind = ticket_type(event)
        theirs = order(event, buyer=UserFactory(), lines=[(kind, 1)])

        response = authenticated_client.get(_order_url(event, theirs.pk))

        assert_response_404(response)

    def test_cancel_expires_the_session_and_frees_the_seats(
        self, authenticated_client, event, active_user, stripe_api
    ):
        kind = ticket_type(event)
        mine = order(event, buyer=active_user, lines=[(kind, 1)])
        stripe_api.add(
            responses.POST,
            f"{API}/checkout/sessions/cs_test_1/expire",
            json={"id": "cs_test_1", "object": "checkout.session"},
        )

        response = authenticated_client.get(_cancel_url(event, mine.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_tickets_url(event),
            messages=[(messages.INFO, "Checkout cancelled. Nothing was charged.")],
        )
        assert TicketOrder.objects.get().status == OrderStatus.EXPIRED
        assert stripe_api.calls[0].request.headers["Stripe-Account"] == ACCOUNT_ID

    def test_cancel_after_stripe_completed_leaves_the_order_to_the_webhook(
        self, authenticated_client, event, active_user, stripe_api
    ):
        kind = ticket_type(event)
        mine = order(event, buyer=active_user, lines=[(kind, 1)])
        stripe_api.add(
            responses.POST,
            f"{API}/checkout/sessions/cs_test_1/expire",
            json={"error": {"type": "invalid_request_error", "message": "complete"}},
            status=HTTPStatus.BAD_REQUEST,
        )

        response = authenticated_client.get(_cancel_url(event, mine.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_tickets_url(event),
            messages=[
                (
                    messages.WARNING,
                    (
                        "Stripe didn't confirm the cancellation. If you didn't pay,"
                        " the tickets go back on sale within the hour."
                    ),
                )
            ],
        )
        assert TicketOrder.objects.get().status == OrderStatus.PENDING

    def test_cancel_of_a_paid_order_shows_the_order(
        self, authenticated_client, event, active_user, stripe_api
    ):
        kind = ticket_type(event)
        mine = order(event, buyer=active_user, lines=[(kind, 1)], status="paid")

        response = authenticated_client.get(_cancel_url(event, mine.pk))

        assert_response(response, HTTPStatus.FOUND, url=_order_url(event, mine.pk))
        assert TicketOrder.objects.get().status == OrderStatus.PAID
        assert not stripe_api.calls

    def test_cancel_link_not_from_stripe_cancels_nothing(
        self, authenticated_client, event, active_user, stripe_api
    ):
        kind = ticket_type(event)
        mine = order(event, buyer=active_user, lines=[(kind, 1)])
        other = order(event, buyer=active_user, lines=[(kind, 1)], session_id="cs_2")

        response = authenticated_client.get(
            _cancel_url(event, mine.pk, token=_SIGNER.sign(str(other.pk)))
        )

        assert_response(response, HTTPStatus.FOUND, url=_order_url(event, mine.pk))
        assert TicketOrder.objects.get(pk=mine.pk).status == OrderStatus.PENDING
        assert not stripe_api.calls
