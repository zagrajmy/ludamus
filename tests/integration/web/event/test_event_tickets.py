"""Buying tickets: the page, Checkout hand-off, the order page, claim, cancel.

How it could go wrong: a free event grows a ticket page; a script holds a
sell-out through guest checkouts; a ticket type id from another event is sold;
seats held by someone still in Checkout are sold twice; Zagrajmy's fee (or a
deal's lower one) or the connected account is wrong on the Checkout Session;
a Stripe failure keeps seats held; a claimed order is shown to someone with
its link, or claimed away from its holder; an order reference from another
event is shown, claimed or cancelled.
"""

import json
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from itertools import count
from urllib.parse import parse_qs, urlencode

import pytest
import responses
from django.contrib import messages
from django.test import Client
from django.urls import reverse

from ludamus.links.db.django.models import SpherePlan, Ticket, TicketOrder
from ludamus.pacts import EventDTO
from ludamus.pacts.tickets import (
    MAX_TICKETS_PER_ORDER,
    EventShopDTO,
    OfferState,
    OrderPageState,
    OrderStatus,
    TicketDTO,
    TicketOfferDTO,
    TicketTypeDTO,
)
from ludamus.specs.tickets import GUEST_CHECKOUTS_PER_WINDOW
from tests.integration.conftest import EventFactory, UserFactory
from tests.integration.stripe_helpers import (
    ACCOUNT_ID,
    API,
    connected_account,
    order,
    ticket_type,
)
from tests.integration.utils import (
    AttributesMatcher,
    assert_response,
    assert_response_404,
)

pytestmark = pytest.mark.usefixtures("stripe_settings")

CHECKOUT_URL = "https://checkout.stripe.com/c/pay/cs_test_new"


def _tickets_url(event):
    return reverse("web:event:event-tickets", kwargs={"event_slug": event.slug})


def _buy_url(event):
    return reverse("web:event:event-tickets-buy", kwargs={"event_slug": event.slug})


def _order_url(event, placed):
    return reverse(
        "web:event:event-ticket-order",
        kwargs={"event_slug": event.slug, "reference": placed.reference},
    )


def _cancel_url(event, placed):
    return reverse(
        "web:event:event-ticket-order-cancel",
        kwargs={"event_slug": event.slug, "reference": placed.reference},
    )


def _claim_url(event, placed):
    return reverse(
        "web:event:event-ticket-order-claim",
        kwargs={"event_slug": event.slug, "reference": placed.reference},
    )


def _sign_in_url(next_path, **extra):
    query = urlencode({"next": next_path, **extra})
    return f"{reverse('web:crowd:auth0:login')}?{query}"


def _order_page_context(event, placed, *, order_matcher, state, claimable):
    here = _order_url(event, placed)
    return {
        "event": EventDTO.model_validate(event),
        "order": order_matcher,
        "state": state,
        "claimable": claimable,
        "sign_in_url": _sign_in_url(here),
        "sign_up_url": _sign_in_url(here, screen_hint="signup"),
    }


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

        response = authenticated_client.get(_tickets_url(event))

        shop = response.context_data["shop"]
        assert shop.viewer_ticket_count == 1 + 1

    def test_unpublished_event_stays_hidden(self, client, sphere):
        hidden = EventFactory(sphere=sphere, publication_time=None)
        ticket_type(hidden)

        response = client.get(_tickets_url(hidden))

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
        assert sent["success_url"] == [f"http://testserver{_order_url(event, created)}"]

    def test_guest_over_the_limit_starts_nothing(self, client, event, stripe_api):
        connected_account(event.sphere)
        kind = ticket_type(event)
        _mock_checkouts(stripe_api)
        for _ in range(GUEST_CHECKOUTS_PER_WINDOW):
            client.post(_buy_url(event), {f"quantity-{kind.pk}": "1"})

        response = client.post(_buy_url(event), {f"quantity-{kind.pk}": "1"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_tickets_url(event),
            messages=[
                (
                    messages.ERROR,
                    (
                        "Too many checkouts from your connection. Wait a few"
                        " minutes, or sign in to buy now."
                    ),
                )
            ],
        )
        assert TicketOrder.objects.count() == GUEST_CHECKOUTS_PER_WINDOW
        assert len(stripe_api.calls) == GUEST_CHECKOUTS_PER_WINDOW

    def test_guest_limit_does_not_bind_a_signed_in_buyer(
        self, authenticated_client, event, stripe_api
    ):
        connected_account(event.sphere)
        kind = ticket_type(event)
        _mock_checkouts(stripe_api)
        guest = Client()
        for _ in range(GUEST_CHECKOUTS_PER_WINDOW + 1):
            guest.post(_buy_url(event), {f"quantity-{kind.pk}": "1"})

        response = authenticated_client.post(
            _buy_url(event), {f"quantity-{kind.pk}": "1"}
        )

        assert_response(response, HTTPStatus.FOUND, url=CHECKOUT_URL)
        assert TicketOrder.objects.count() == GUEST_CHECKOUTS_PER_WINDOW + 1

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
            url=_tickets_url(event),
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
        assert sent["success_url"] == [f"http://testserver{_order_url(event, created)}"]
        assert sent["cancel_url"] == [f"http://testserver{_cancel_url(event, created)}"]

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
            url=_tickets_url(event),
            messages=[(messages.ERROR, "Choose how many tickets you want.")],
        )
        assert not TicketOrder.objects.exists()


class TestEventTicketOrderPage:
    def test_guest_order_is_open_to_whoever_has_its_link(self, client, event):
        kind = ticket_type(event)
        guests = order(event, buyer=None, lines=[(kind, 1)], status="paid")
        ticket = Ticket.objects.create(
            order=guests, ticket_type=kind, code="GUEST22222"
        )

        response = client.get(_order_url(event, guests))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/ticket-order.html",
            context_data=_order_page_context(
                event,
                guests,
                order_matcher=AttributesMatcher(
                    pk=guests.pk,
                    buyer_id=None,
                    status=OrderStatus.PAID,
                    tickets=[
                        TicketDTO(
                            pk=ticket.pk,
                            code="GUEST22222",
                            ticket_type_name="Weekend pass",
                        )
                    ],
                ),
                state=OrderPageState.PAID,
                claimable=True,
            ),
        )

    def test_signed_in_visitor_may_claim_a_guest_order(
        self, authenticated_client, event
    ):
        guests = order(event, buyer=None, lines=[(ticket_type(event), 1)])

        response = authenticated_client.get(_order_url(event, guests))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/ticket-order.html",
            context_data=_order_page_context(
                event,
                guests,
                order_matcher=AttributesMatcher(pk=guests.pk, buyer_id=None),
                state=OrderPageState.CONFIRMING,
                claimable=True,
            ),
        )

    def test_claimed_order_sends_a_signed_out_visitor_to_log_in(
        self, client, event, active_user
    ):
        mine = order(event, buyer=active_user, lines=[(ticket_type(event), 1)])
        url = _order_url(event, mine)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_paid_order_shows_its_tickets(
        self, authenticated_client, event, active_user
    ):
        kind = ticket_type(event)
        mine = order(event, buyer=active_user, lines=[(kind, 2)], status="paid")
        first = Ticket.objects.create(
            order=mine, ticket_type=kind, holder=active_user, code="AAAAAAAA22"
        )
        second = Ticket.objects.create(
            order=mine, ticket_type=kind, holder=active_user, code="AAAAAAAA33"
        )

        response = authenticated_client.get(_order_url(event, mine))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/ticket-order.html",
            context_data=_order_page_context(
                event,
                mine,
                order_matcher=AttributesMatcher(
                    pk=mine.pk,
                    status=OrderStatus.PAID,
                    total=10_000,
                    tickets=[
                        TicketDTO(
                            pk=first.pk,
                            code="AAAAAAAA22",
                            ticket_type_name="Weekend pass",
                        ),
                        TicketDTO(
                            pk=second.pk,
                            code="AAAAAAAA33",
                            ticket_type_name="Weekend pass",
                        ),
                    ],
                ),
                state=OrderPageState.PAID,
                claimable=False,
            ),
        )

    @pytest.mark.parametrize(
        ("status", "hold_minutes", "state"),
        (
            pytest.param(
                OrderStatus.PENDING, 30, OrderPageState.CONFIRMING, id="paying-now"
            ),
            pytest.param(
                OrderStatus.PENDING,
                -1,
                OrderPageState.CONFIRMATION_LATE,
                id="hold-over-webhook-late",
            ),
            pytest.param(
                OrderStatus.AWAITING_PAYMENT,
                30,
                OrderPageState.AWAITING_TRANSFER,
                id="bank-transfer",
            ),
            pytest.param(
                OrderStatus.REFUNDED, 30, OrderPageState.REFUNDED, id="refunded"
            ),
            pytest.param(
                OrderStatus.EXPIRED, 30, OrderPageState.NOT_COMPLETED, id="expired"
            ),
            pytest.param(
                OrderStatus.FAILED, 30, OrderPageState.NOT_COMPLETED, id="failed"
            ),
        ),
    )
    def test_unpaid_order_says_where_it_stands(
        self, authenticated_client, event, active_user, *, status, hold_minutes, state
    ):
        mine = order(
            event,
            buyer=active_user,
            lines=[(ticket_type(event), 1)],
            status=status,
            hold_minutes=hold_minutes,
        )

        response = authenticated_client.get(_order_url(event, mine))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/ticket-order.html",
            context_data=_order_page_context(
                event,
                mine,
                order_matcher=AttributesMatcher(pk=mine.pk, status=status, tickets=[]),
                state=state,
                claimable=False,
            ),
        )

    def test_order_under_another_events_url_is_not_found(
        self, authenticated_client, event
    ):
        elsewhere = EventFactory(sphere=event.sphere)
        guests = order(elsewhere, buyer=None, lines=[(ticket_type(elsewhere), 1)])

        response = authenticated_client.get(_order_url(event, guests))

        assert_response_404(response)

    def test_someone_elses_order_is_not_found(self, authenticated_client, event):
        theirs = order(event, buyer=UserFactory(), lines=[(ticket_type(event), 1)])

        response = authenticated_client.get(_order_url(event, theirs))

        assert_response_404(response)


class TestEventTicketOrderClaimActionView:
    def test_moves_the_order_and_its_tickets_into_the_account(
        self, authenticated_client, event, active_user
    ):
        kind = ticket_type(event)
        guests = order(event, buyer=None, lines=[(kind, 2)], status="paid")
        Ticket.objects.create(order=guests, ticket_type=kind, code="GUEST22222")
        Ticket.objects.create(order=guests, ticket_type=kind, code="GUEST33333")

        response = authenticated_client.post(_claim_url(event, guests))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_order_url(event, guests),
            messages=[
                (
                    messages.SUCCESS,
                    "The tickets are in your account. They're under My tickets.",
                )
            ],
        )
        guests.refresh_from_db()
        assert guests.buyer_id == active_user.pk
        assert set(guests.tickets.values_list("holder_id", flat=True)) == {
            active_user.pk
        }

    def test_claimed_order_is_closed_to_its_link_from_then_on(
        self, authenticated_client, event
    ):
        guests = order(event, buyer=None, lines=[(ticket_type(event), 1)])
        url = _order_url(event, guests)
        authenticated_client.post(_claim_url(event, guests))

        response = Client().get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_own_order_stays_as_it_is(self, authenticated_client, event, active_user):
        mine = order(event, buyer=active_user, lines=[(ticket_type(event), 1)])

        response = authenticated_client.post(_claim_url(event, mine))

        assert_response(response, HTTPStatus.FOUND, url=_order_url(event, mine))
        mine.refresh_from_db()
        assert mine.buyer_id == active_user.pk

    def test_someone_elses_order_is_not_found_and_stays_theirs(
        self, authenticated_client, event
    ):
        holder = UserFactory()
        kind = ticket_type(event)
        theirs = order(event, buyer=holder, lines=[(kind, 1)], status="paid")
        Ticket.objects.create(
            order=theirs, ticket_type=kind, holder=holder, code="THEIRS2222"
        )

        response = authenticated_client.post(_claim_url(event, theirs))

        assert_response_404(response)
        theirs.refresh_from_db()
        assert theirs.buyer_id == holder.pk
        assert list(theirs.tickets.values_list("holder_id", flat=True)) == [holder.pk]

    def test_order_of_another_event_is_not_found_and_stays_unclaimed(
        self, authenticated_client, event
    ):
        elsewhere = EventFactory(sphere=event.sphere)
        guests = order(elsewhere, buyer=None, lines=[(ticket_type(elsewhere), 1)])

        response = authenticated_client.post(_claim_url(event, guests))

        assert_response_404(response)
        guests.refresh_from_db()
        assert guests.buyer_id is None

    def test_signed_out_visitor_is_sent_to_log_in_first(self, client, event):
        guests = order(event, buyer=None, lines=[(ticket_type(event), 1)])

        response = client.post(_claim_url(event, guests))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=f"/crowd/login-required/?next={_order_url(event, guests)}",
        )
        guests.refresh_from_db()
        assert guests.buyer_id is None


class TestEventTicketOrderCancelActionView:
    def test_cancel_expires_the_session_and_frees_the_seats(
        self, authenticated_client, event, active_user, stripe_api
    ):
        mine = order(event, buyer=active_user, lines=[(ticket_type(event), 1)])
        stripe_api.add(
            responses.POST,
            f"{API}/checkout/sessions/cs_test_1/expire",
            json={"id": "cs_test_1", "object": "checkout.session"},
        )

        response = authenticated_client.get(_cancel_url(event, mine))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_tickets_url(event),
            messages=[(messages.INFO, "Checkout cancelled. Nothing was charged.")],
        )
        assert TicketOrder.objects.get().status == OrderStatus.EXPIRED
        assert stripe_api.calls[0].request.headers["Stripe-Account"] == ACCOUNT_ID

    def test_guest_cancels_by_the_link_stripe_was_given(
        self, client, event, stripe_api
    ):
        guests = order(event, buyer=None, lines=[(ticket_type(event), 1)])
        stripe_api.add(
            responses.POST,
            f"{API}/checkout/sessions/cs_test_1/expire",
            json={"id": "cs_test_1", "object": "checkout.session"},
        )

        response = client.get(_cancel_url(event, guests))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_tickets_url(event),
            messages=[(messages.INFO, "Checkout cancelled. Nothing was charged.")],
        )
        assert TicketOrder.objects.get().status == OrderStatus.EXPIRED

    def test_cancel_after_stripe_completed_leaves_the_order_to_the_webhook(
        self, authenticated_client, event, active_user, stripe_api
    ):
        mine = order(event, buyer=active_user, lines=[(ticket_type(event), 1)])
        stripe_api.add(
            responses.POST,
            f"{API}/checkout/sessions/cs_test_1/expire",
            json={"error": {"type": "invalid_request_error", "message": "complete"}},
            status=HTTPStatus.BAD_REQUEST,
        )

        response = authenticated_client.get(_cancel_url(event, mine))

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
        mine = order(
            event, buyer=active_user, lines=[(ticket_type(event), 1)], status="paid"
        )

        response = authenticated_client.get(_cancel_url(event, mine))

        assert_response(response, HTTPStatus.FOUND, url=_order_url(event, mine))
        assert TicketOrder.objects.get().status == OrderStatus.PAID
        assert not stripe_api.calls

    def test_signed_out_cancel_of_a_claimed_order_cancels_nothing(
        self, client, event, active_user, stripe_api
    ):
        mine = order(event, buyer=active_user, lines=[(ticket_type(event), 1)])

        response = client.get(_cancel_url(event, mine))

        assert_response(response, HTTPStatus.FOUND, url=_tickets_url(event))
        assert TicketOrder.objects.get().status == OrderStatus.PENDING
        assert not stripe_api.calls

    def test_cancel_of_someone_elses_order_is_not_found(
        self, authenticated_client, event, stripe_api
    ):
        theirs = order(event, buyer=UserFactory(), lines=[(ticket_type(event), 1)])

        response = authenticated_client.get(_cancel_url(event, theirs))

        assert_response_404(response)
        assert TicketOrder.objects.get().status == OrderStatus.PENDING
        assert not stripe_api.calls

    def test_cancel_of_another_events_order_is_not_found(
        self, authenticated_client, event, stripe_api
    ):
        elsewhere = EventFactory(sphere=event.sphere)
        guests = order(elsewhere, buyer=None, lines=[(ticket_type(elsewhere), 1)])

        response = authenticated_client.get(_cancel_url(event, guests))

        assert_response_404(response)
        assert TicketOrder.objects.get().status == OrderStatus.PENDING
        assert not stripe_api.calls
