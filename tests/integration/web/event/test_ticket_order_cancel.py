"""Stripe's "back" link from Checkout: cancelling frees the order's seats.

How it could go wrong: a paid order is cancelled; a guest cannot cancel by
the link Stripe was given; a signed-out visitor, someone else, or a reference
from another event cancels a buyer's checkout; a cancel Stripe refused frees
seats the buyer may have paid for.
"""

from http import HTTPStatus

import pytest
import responses
from django.contrib import messages

from ludamus.links.db.django.models import TicketOrder
from ludamus.pacts.tickets import OrderStatus
from tests.integration.conftest import EventFactory, UserFactory
from tests.integration.stripe_helpers import (
    ACCOUNT_ID,
    API,
    GUEST_CLIENT,
    cancel_url,
    order,
    order_url,
    ticket_type,
    tickets_url,
)
from tests.integration.utils import assert_response, assert_response_404

pytestmark = pytest.mark.usefixtures("stripe_settings")


def _mock_expire(stripe_api, **reply):
    stripe_api.add(
        responses.POST,
        f"{API}/checkout/sessions/cs_test_1/expire",
        **(reply or {"json": {"id": "cs_test_1", "object": "checkout.session"}}),
    )


class TestEventTicketOrderCancelActionView:
    def test_cancel_expires_the_session_and_frees_the_seats(
        self, authenticated_client, event, active_user, stripe_api
    ):
        mine = order(event, buyer=active_user, lines=[(ticket_type(event), 1)])
        _mock_expire(stripe_api)

        response = authenticated_client.get(cancel_url(event, mine))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=tickets_url(event),
            messages=[(messages.INFO, "Checkout cancelled. Nothing was charged.")],
        )
        assert TicketOrder.objects.get().status == OrderStatus.EXPIRED
        assert stripe_api.calls[0].request.headers["Stripe-Account"] == ACCOUNT_ID

    def test_guest_cancels_by_the_link_stripe_was_given(
        self, client, event, stripe_api
    ):
        guests = order(
            event,
            buyer=None,
            lines=[(ticket_type(event), 1)],
            guest_client=GUEST_CLIENT,
        )
        _mock_expire(stripe_api)

        response = client.get(cancel_url(event, guests))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=tickets_url(event),
            messages=[(messages.INFO, "Checkout cancelled. Nothing was charged.")],
        )
        # Its seats are free, so the guest's network no longer counts it.
        cancelled = TicketOrder.objects.get()
        assert (cancelled.status, cancelled.guest_client) == (OrderStatus.EXPIRED, "")

    def test_cancel_after_stripe_completed_leaves_the_order_to_the_webhook(
        self, authenticated_client, event, active_user, stripe_api
    ):
        mine = order(event, buyer=active_user, lines=[(ticket_type(event), 1)])
        _mock_expire(
            stripe_api,
            json={"error": {"type": "invalid_request_error", "message": "complete"}},
            status=HTTPStatus.BAD_REQUEST,
        )

        response = authenticated_client.get(cancel_url(event, mine))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=tickets_url(event),
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
        mine = order(
            event, buyer=active_user, lines=[(ticket_type(event), 1)], status="paid"
        )

        response = authenticated_client.get(cancel_url(event, mine))

        assert_response(response, HTTPStatus.FOUND, url=order_url(event, mine))
        assert TicketOrder.objects.get().status == OrderStatus.PAID
        assert not stripe_api.calls

    def test_signed_out_cancel_of_a_claimed_order_cancels_nothing(
        self, client, event, active_user, stripe_api
    ):
        mine = order(event, buyer=active_user, lines=[(ticket_type(event), 1)])

        response = client.get(cancel_url(event, mine))

        assert_response(response, HTTPStatus.FOUND, url=tickets_url(event))
        assert TicketOrder.objects.get().status == OrderStatus.PENDING
        assert not stripe_api.calls

    def test_cancel_of_someone_elses_order_is_not_found(
        self, authenticated_client, event, stripe_api
    ):
        theirs = order(event, buyer=UserFactory(), lines=[(ticket_type(event), 1)])

        response = authenticated_client.get(cancel_url(event, theirs))

        assert_response_404(response)
        assert TicketOrder.objects.get().status == OrderStatus.PENDING
        assert not stripe_api.calls

    def test_cancel_of_another_events_order_is_not_found(
        self, authenticated_client, event, stripe_api
    ):
        elsewhere = EventFactory(sphere=event.sphere)
        guests = order(elsewhere, buyer=None, lines=[(ticket_type(elsewhere), 1)])

        response = authenticated_client.get(cancel_url(event, guests))

        assert_response_404(response)
        assert TicketOrder.objects.get().status == OrderStatus.PENDING
        assert not stripe_api.calls
