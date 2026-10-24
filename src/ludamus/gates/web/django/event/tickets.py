"""Buying tickets: the event's ticket page, Checkout, and the order it made.

The page lists what is on sale; buying hands the browser to Stripe Checkout,
and Stripe sends it back to the order page (paid) or through the cancel action
(the buyer changed their mind, which releases the seats at once).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, assert_never
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.signing import BadSignature, Signer
from django.http import Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.helpers import account_email, read_public_event
from ludamus.pacts.legacy import NotFoundError
from ludamus.pacts.tickets import (
    MAX_TICKETS_PER_ORDER,
    AbandonOutcome,
    CheckoutOutcome,
    CheckoutUrls,
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
_CANCEL_SIGNER = Signer(salt="ticket-checkout-cancel")


def _signed_for(token: str, *, pk: int) -> bool:
    try:
        return _CANCEL_SIGNER.unsign(token) == str(pk)
    except BadSignature:
        return False


def _tickets_url(slug: str) -> str:
    return reverse("web:event:event-tickets", kwargs={"event_slug": slug})


def _order_url(slug: str, pk: int) -> str:
    return reverse(
        "web:event:event-ticket-order", kwargs={"event_slug": slug, "pk": pk}
    )


def _cancel_url(slug: str, pk: int) -> str:
    # Signed: only the link handed to Stripe cancels a checkout.
    path = reverse(
        "web:event:event-ticket-order-cancel", kwargs={"event_slug": slug, "pk": pk}
    )
    return f"{path}?{urlencode({'token': _CANCEL_SIGNER.sign(str(pk))})}"


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
        if (buyer_id := request.context.current_user_id) is None:
            return redirect_to_login(_tickets_url(event.slug))
        if not (email := account_email(request)):
            messages.error(
                request,
                _("Add an email address to your profile first: tickets go there."),
            )
            return redirect(_tickets_url(event.slug))
        if (quantities := _quantities(request)) is None:
            messages.error(request, _("Choose how many tickets you want."))
            return redirect(_tickets_url(event.slug))

        started = request.services.ticket_sales.start_checkout(
            event=event,
            buyer_id=buyer_id,
            email=email,
            quantities=quantities,
            urls=CheckoutUrls(
                success=lambda pk: request.build_absolute_uri(
                    _order_url(event.slug, pk)
                ),
                cancel=lambda pk: request.build_absolute_uri(
                    _cancel_url(event.slug, pk)
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
    def get(request: RootRequest, event_slug: str, pk: int) -> HttpResponse:
        event = read_public_event(request, event_slug)
        if (buyer_id := request.context.current_user_id) is None:
            return redirect_to_login(request.get_full_path())
        try:
            page = request.services.ticket_sales.order(
                buyer_id=buyer_id, event_id=event.pk, pk=pk
            )
        except NotFoundError as exc:
            raise Http404 from exc
        return TemplateResponse(
            request,
            "chronology/ticket-order.html",
            {"event": event, "order": page.order, "state": page.state},
        )


class EventTicketOrderCancelActionView(View):
    """Stripe's "back" link: the buyer left Checkout, so free the seats now.

    A GET because Stripe can only redirect; it acts on the signed-in buyer's
    own unpaid order and nothing else, and only through the signed link handed
    to Stripe, so another site cannot cancel a buyer's checkout under them.
    """

    request: RootRequest

    @staticmethod
    def get(request: RootRequest, event_slug: str, pk: int) -> HttpResponse:
        event = read_public_event(request, event_slug)
        if (buyer_id := request.context.current_user_id) is None:
            return redirect(_tickets_url(event.slug))
        if not _signed_for(request.GET.get("token", ""), pk=pk):
            logger.warning("Ticket checkout cancel without a valid token: order=%s", pk)
            return redirect(_order_url(event.slug, pk))
        try:
            outcome = request.services.ticket_sales.abandon_checkout(
                buyer_id=buyer_id, event_id=event.pk, pk=pk
            )
        except NotFoundError as exc:
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
                return redirect(_order_url(event.slug, pk))
            case _:
                assert_never(outcome)
        return redirect(_tickets_url(event.slug))
