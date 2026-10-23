"""Buying tickets: the event's ticket page, Checkout, and the order it made.

The page lists what is on sale; buying hands the browser to Stripe Checkout,
and Stripe sends it back to the order page (paid) or through the cancel action
(the buyer changed their mind, which releases the seats at once).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.http import Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.helpers import read_public_event
from ludamus.pacts.legacy import NotFoundError
from ludamus.pacts.tickets import (
    MAX_TICKETS_PER_ORDER,
    CheckoutOutcome,
    CheckoutUrls,
    OrderStatus,
)

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.gates.web.django.entities import RootRequest
    from ludamus.pacts import EventDTO
    from ludamus.pacts.tickets import EventShopDTO

logger = logging.getLogger(__name__)

_QUANTITY_PREFIX = "quantity-"


def _tickets_url(slug: str) -> str:
    return reverse("web:event:event-tickets", kwargs={"event_slug": slug})


def _shop(request: RootRequest, event: EventDTO) -> EventShopDTO:
    return request.services.ticket_sales.shop(
        sphere_id=request.context.current_sphere_id,
        event_id=event.pk,
        viewer_id=request.context.current_user_id,
        closes_at=event.end_time,
    )


def _email(request: RootRequest) -> str:
    return request.user.email if request.user.is_authenticated else ""


def _quantities(request: RootRequest) -> dict[int, int] | None:
    # Format only: ints in range. Whether the type exists, is on sale and has
    # seats left is the service's call.
    quantities: dict[int, int] = {}
    for key in request.POST:
        value = request.POST.get(key, "")
        if not key.startswith(_QUANTITY_PREFIX) or not value:
            continue
        raw_pk = key.removeprefix(_QUANTITY_PREFIX)
        if not (raw_pk.isdecimal() and value.isdecimal()):
            return None
        if (count := int(value)) > MAX_TICKETS_PER_ORDER:
            return None
        quantities[int(raw_pk)] = count
    return quantities


def _outcome_message(outcome: CheckoutOutcome) -> str:
    match outcome:
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
        case _:
            return _(
                "We couldn't reach the payment provider. Nothing was charged; try"
                " again in a moment."
            )


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
        if not (email := _email(request)):
            messages.error(
                request,
                _("Add an email address to your profile first: tickets go there."),
            )
            return redirect(_tickets_url(event.slug))
        if (quantities := _quantities(request)) is None:
            messages.error(request, _("Choose how many tickets you want."))
            return redirect(_tickets_url(event.slug))

        started = request.services.ticket_sales.start_checkout(
            sphere_id=request.context.current_sphere_id,
            event_id=event.pk,
            buyer_id=buyer_id,
            email=email,
            quantities=quantities,
            urls=CheckoutUrls(
                success=_OrderUrl(
                    request=request,
                    name="web:event:event-ticket-order",
                    slug=event.slug,
                ),
                cancel=_OrderUrl(
                    request=request,
                    name="web:event:event-ticket-order-cancel",
                    slug=event.slug,
                ),
            ),
            closes_at=event.end_time,
        )
        logger.info(
            "Ticket checkout: event=%s buyer=%s outcome=%s",
            event.pk,
            buyer_id,
            started.outcome,
        )
        if started.outcome is CheckoutOutcome.STARTED:
            return redirect(started.url)
        messages.error(request, _outcome_message(started.outcome))
        return redirect(_tickets_url(event.slug))


class _OrderUrl:
    """An order's absolute URL on this sphere's domain, built once its pk exists."""

    def __init__(self, *, request: RootRequest, name: str, slug: str) -> None:
        self._request = request
        self._name = name
        self._slug = slug

    def __call__(self, order_pk: int) -> str:
        return self._request.build_absolute_uri(
            reverse(self._name, kwargs={"event_slug": self._slug, "pk": order_pk})
        )


class EventTicketOrderPageView(View):
    """The buyer's order: confirming, paid with its tickets, or not completed."""

    request: RootRequest

    @staticmethod
    def get(request: RootRequest, event_slug: str, pk: int) -> HttpResponse:
        event = read_public_event(request, event_slug)
        if (buyer_id := request.context.current_user_id) is None:
            return redirect_to_login(request.get_full_path())
        try:
            order = request.services.ticket_sales.order(
                buyer_id=buyer_id, event_id=event.pk, pk=pk
            )
        except NotFoundError as exc:
            raise Http404 from exc
        return TemplateResponse(
            request,
            "chronology/ticket-order.html",
            {
                "event": event,
                "order": order,
                # Stripe's webhook usually lands within seconds of the
                # redirect; until then the page checks back on its own.
                "confirming": (
                    order.status in {OrderStatus.PENDING, OrderStatus.AWAITING_PAYMENT}
                ),
            },
        )


class EventTicketOrderCancelActionView(View):
    """Stripe's "back" link: the buyer left Checkout, so free the seats now.

    A GET because Stripe can only redirect; it acts on the signed-in buyer's
    own unpaid order and nothing else.
    """

    request: RootRequest

    @staticmethod
    def get(request: RootRequest, event_slug: str, pk: int) -> HttpResponse:
        event = read_public_event(request, event_slug)
        if (buyer_id := request.context.current_user_id) is None:
            return redirect(_tickets_url(event.slug))
        try:
            request.services.ticket_sales.abandon_checkout(
                buyer_id=buyer_id, event_id=event.pk, pk=pk
            )
        except NotFoundError as exc:
            raise Http404 from exc
        messages.info(request, _("Checkout cancelled. Nothing was charged."))
        return redirect(_tickets_url(event.slug))
