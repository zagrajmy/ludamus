"""Buying tickets: the event's ticket page, Checkout, and the order it made.

The page lists what is on sale; buying hands the browser to Stripe Checkout,
and Stripe sends it back to the order page (paid) or through the cancel action
(the buyer changed their mind, which releases the seats at once).

Nobody needs an account to buy. The order page's address carries the order's
secret reference; a guest who signs in there can claim the order, and its
tickets, into the account they signed in to, new or old.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, assert_never
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.http import Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.helpers import (
    account_email,
    get_client_ip,
    read_public_event,
)
from ludamus.pacts.legacy import NotFoundError
from ludamus.pacts.tickets import (
    MAX_TICKETS_PER_ORDER,
    AbandonOutcome,
    CheckoutOutcome,
    CheckoutUrls,
    ClaimOutcome,
)

if TYPE_CHECKING:

    from django.http import HttpResponse

    from ludamus.gates.web.django.entities import RootRequest
    from ludamus.pacts import EventDTO
    from ludamus.pacts.tickets import EventShopDTO

logger = logging.getLogger(__name__)

_QUANTITY_PREFIX = "quantity-"
# Far above any real ticket-type pk or quantity, far below int()'s 4300-digit cap.
_MAX_DIGITS = 9


def _tickets_url(slug: str) -> str:
    return reverse("web:event:event-tickets", kwargs={"event_slug": slug})


def _order_url(slug: str, reference: str) -> str:
    return reverse(
        "web:event:event-ticket-order",
        kwargs={"event_slug": slug, "reference": reference},
    )


def _cancel_url(slug: str, reference: str) -> str:
    return reverse(
        "web:event:event-ticket-order-cancel",
        kwargs={"event_slug": slug, "reference": reference},
    )


def _sign_in_url(next_path: str, *, signup: bool) -> str:
    # Auth0 opens its signup screen when asked; either way the buyer comes
    # back to the order page, signed in, to claim it.
    params = {"next": next_path} | ({"screen_hint": "signup"} if signup else {})
    return f"{reverse('web:crowd:auth0:login')}?{urlencode(params)}"


def _shop(request: RootRequest, event: EventDTO) -> EventShopDTO:
    return request.services.ticket_sales.shop(
        event=event, viewer_id=request.context.current_user_id
    )


def _is_whole_number(text: str) -> bool:
    return text.isascii() and text.isdecimal() and len(text) <= _MAX_DIGITS


def _quantities(request: RootRequest) -> dict[int, int] | None:
    # Format only: whole numbers. How many may be bought, and whether the type
    # exists, is on sale and has seats left, is the service's call.
    quantities: dict[int, int] = {}
    for key in request.POST:
        value = request.POST.get(key, "")
        if not key.startswith(_QUANTITY_PREFIX) or not value:
            continue
        raw_pk = key.removeprefix(_QUANTITY_PREFIX)
        if not (_is_whole_number(raw_pk) and _is_whole_number(value)):
            return None
        quantities[int(raw_pk)] = int(value)
    return quantities


def _refusal_message(outcome: CheckoutOutcome) -> str | None:
    match outcome:
        case CheckoutOutcome.STARTED:
            return None
        case CheckoutOutcome.NOTHING_SELECTED:
            return _("Choose how many tickets you want.")
        case CheckoutOutcome.TOO_MANY:
            return _("You can buy up to %(limit)d tickets in one order.") % {
                "limit": MAX_TICKETS_PER_ORDER
            }
        case CheckoutOutcome.SOLD_OUT:
            return _("Not enough tickets left. Pick fewer, or another ticket type.")
        case CheckoutOutcome.NOT_ON_SALE:
            return _("That ticket isn't on sale right now.")
        case CheckoutOutcome.SALES_CLOSED:
            return _("Ticket sales for this event are paused. Try again later.")
        case CheckoutOutcome.PROVIDER_ERROR:
            return _(
                "We couldn't reach the payment provider. Nothing was charged; try"
                " again in a moment."
            )
        case _:
            assert_never(outcome)


class EventTicketsPageView(View):
    request: RootRequest

    @staticmethod
    def get(request: RootRequest, event_slug: str) -> HttpResponse:
        event = read_public_event(request, event_slug)
        shop = _shop(request, event)
        # A free event has no ticket page at all.
        if not shop.has_tickets:
            raise Http404
        return TemplateResponse(
            request,
            "chronology/tickets.html",
            {"event": event, "shop": shop, "max_per_order": MAX_TICKETS_PER_ORDER},
        )


class EventTicketsBuyActionView(View):
    request: RootRequest
    http_method_names = ("post",)

    @staticmethod
    def post(request: RootRequest, event_slug: str) -> HttpResponse:
        event = read_public_event(request, event_slug)
        if (quantities := _quantities(request)) is None:
            messages.error(request, _("Choose how many tickets you want."))
            return redirect(_tickets_url(event.slug))
        buyer_id = request.context.current_user_id
        if (
            buyer_id is None
            and not request.services.ticket_sales.guest_checkout_allowed(
                ip=get_client_ip(request), event_id=event.pk
            )
        ):
            messages.error(
                request,
                _(
                    "Too many checkouts from your connection. Wait a few minutes,"
                    " or sign in to buy now."
                ),
            )
            return redirect(_tickets_url(event.slug))

        started = request.services.ticket_sales.start_checkout(
            event=event,
            buyer_id=buyer_id,
            # Empty for a guest, or an account without one: Checkout asks.
            email=account_email(request),
            quantities=quantities,
            urls=CheckoutUrls(
                success=lambda reference: request.build_absolute_uri(
                    _order_url(event.slug, reference)
                ),
                cancel=lambda reference: request.build_absolute_uri(
                    _cancel_url(event.slug, reference)
                ),
            ),
        )
        logger.info(
            "Ticket checkout: event=%s buyer=%s outcome=%s",
            event.pk,
            buyer_id,
            started.outcome,
        )
        if (refusal := _refusal_message(started.outcome)) is None:
            return redirect(started.url)
        messages.error(request, refusal)
        return redirect(_tickets_url(event.slug))


class EventTicketOrderPageView(View):
    """The buyer's order: confirming, paid with its tickets, or not completed."""

    request: RootRequest

    @staticmethod
    def get(request: RootRequest, event_slug: str, reference: str) -> HttpResponse:
        event = read_public_event(request, event_slug)
        viewer_id = request.context.current_user_id
        try:
            page = request.services.ticket_sales.order(
                event_id=event.pk, reference=reference, viewer_id=viewer_id
            )
        except NotFoundError as exc:
            if viewer_id is None:
                # Claimed into an account: its holder signs in to see it.
                return redirect_to_login(request.get_full_path())
            raise Http404 from exc
        here = request.get_full_path()
        return TemplateResponse(
            request,
            "chronology/ticket-order.html",
            {
                "event": event,
                "order": page.order,
                "state": page.state,
                "claimable": page.claimable,
                "sign_in_url": _sign_in_url(here, signup=False),
                "sign_up_url": _sign_in_url(here, signup=True),
            },
        )


class EventTicketOrderClaimActionView(View):
    """Keep a guest's order: it and its tickets move into the signed-in account."""

    request: RootRequest
    http_method_names = ("post",)

    @staticmethod
    def post(request: RootRequest, event_slug: str, reference: str) -> HttpResponse:
        event = read_public_event(request, event_slug)
        if (user_id := request.context.current_user_id) is None:
            return redirect_to_login(_order_url(event.slug, reference))
        try:
            outcome = request.services.ticket_sales.claim_order(
                event_id=event.pk, reference=reference, user_id=user_id
            )
        except NotFoundError as exc:
            raise Http404 from exc
        match outcome:
            case ClaimOutcome.CLAIMED:
                messages.success(
                    request,
                    _("The tickets are in your account. They're under My tickets."),
                )
            case ClaimOutcome.ALREADY_YOURS:
                pass
            case _:
                assert_never(outcome)
        return redirect(_order_url(event.slug, reference))


class EventTicketOrderCancelActionView(View):
    """Stripe's "back" link: the buyer left Checkout, so free the seats now.

    A GET because Stripe can only redirect. It acts only on an unpaid order
    its viewer may see, found by the secret reference in the link handed to
    Stripe, so another site cannot cancel a buyer's checkout under them.
    """

    request: RootRequest

    @staticmethod
    def get(request: RootRequest, event_slug: str, reference: str) -> HttpResponse:
        event = read_public_event(request, event_slug)
        viewer_id = request.context.current_user_id
        try:
            outcome = request.services.ticket_sales.abandon_checkout(
                event_id=event.pk, reference=reference, viewer_id=viewer_id
            )
        except NotFoundError as exc:
            if viewer_id is None:
                return redirect(_tickets_url(event.slug))
            raise Http404 from exc
        match outcome:
            case AbandonOutcome.CANCELLED:
                messages.info(request, _("Checkout cancelled. Nothing was charged."))
            case AbandonOutcome.UNCONFIRMED:
                messages.warning(
                    request,
                    _(
                        "Stripe didn't confirm the cancellation. If you didn't pay,"
                        " the tickets go back on sale within the hour."
                    ),
                )
            case AbandonOutcome.SETTLED:
                return redirect(_order_url(event.slug, reference))
            case _:
                assert_never(outcome)
        return redirect(_tickets_url(event.slug))
