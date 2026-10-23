"""The event's Tickets page: what it sells, what sold, and refunds."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, assert_never

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.event.panel.forms import TicketTypeForm
from ludamus.gates.web.django.event.panel.views.base import (
    EventContextMixin,
    EventPanelAccessMixin,
    EventPanelRequest,
    PanelContext,
)
from ludamus.pacts.legacy import NotFoundError, RedirectError
from ludamus.pacts.tickets import RefundOutcome, TicketTypeData

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.pacts import EventDTO
    from ludamus.pacts.tickets import TicketTypeDTO

logger = logging.getLogger(__name__)

_TICKETS_URL = "panel:tickets"
_FORM_TEMPLATE = "panel/ticket-type-form.html"


def _not_found(slug: str) -> RedirectError:
    return RedirectError(
        reverse(_TICKETS_URL, kwargs={"slug": slug}), error=_("Ticket type not found.")
    )


def _data(form: TicketTypeForm) -> TicketTypeData:
    return {
        "name": form.cleaned_data["name"],
        "description": form.cleaned_data["description"],
        "price": form.cleaned_data["price"],
        "quantity": form.cleaned_data["quantity"],
        "sales_start": form.cleaned_data["sales_start"],
        "sales_end": form.cleaned_data["sales_end"],
    }


class TicketsViewMixin(EventContextMixin):
    request: EventPanelRequest

    def page_context(self, slug: str) -> tuple[PanelContext, EventDTO]:
        context, current_event = self.require_event_context(slug)
        context["active_nav"] = "tickets"
        return context, current_event

    def render_form(
        self, *, slug: str, form: TicketTypeForm, ticket_type: TicketTypeDTO | None
    ) -> HttpResponse:
        context, _current_event = self.page_context(slug)
        context.update({"form": form, "ticket_type": ticket_type})
        return TemplateResponse(self.request, _FORM_TEMPLATE, context)


class EventTicketsPageView(EventPanelAccessMixin, TicketsViewMixin, View):
    request: EventPanelRequest

    def get(self, _request: EventPanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.page_context(slug)
        context["page"] = self.request.services.ticket_panel.page(
            sphere_id=self.request.context.current_sphere_id, event_id=current_event.pk
        )
        return TemplateResponse(self.request, "panel/tickets.html", context)


class TicketTypeCreatePageView(EventPanelAccessMixin, TicketsViewMixin, View):
    request: EventPanelRequest

    def get(self, _request: EventPanelRequest, slug: str) -> HttpResponse:
        return self.render_form(slug=slug, form=TicketTypeForm(), ticket_type=None)

    def post(self, _request: EventPanelRequest, slug: str) -> HttpResponse:
        form = TicketTypeForm(self.request.POST)
        if not form.is_valid():
            return self.render_form(slug=slug, form=form, ticket_type=None)
        current_event = self.require_current_event(slug)
        created = self.request.services.ticket_panel.create_type(
            event_id=current_event.pk, data=_data(form)
        )
        logger.info(
            "Ticket type created: event=%s type=%s price=%s by=%s",
            current_event.pk,
            created.pk,
            created.price,
            self.request.context.current_user_id,
        )
        messages.success(self.request, _("Ticket type added."))
        return redirect(_TICKETS_URL, slug=slug)


class TicketTypeEditPageView(EventPanelAccessMixin, TicketsViewMixin, View):
    request: EventPanelRequest

    def get(self, _request: EventPanelRequest, slug: str, pk: int) -> HttpResponse:
        ticket_type = self._read(slug=slug, pk=pk)
        return self.render_form(
            slug=slug,
            form=TicketTypeForm(
                initial=ticket_type.model_dump(
                    include={
                        "name",
                        "description",
                        "price",
                        "quantity",
                        "sales_start",
                        "sales_end",
                    }
                )
            ),
            ticket_type=ticket_type,
        )

    def post(self, _request: EventPanelRequest, slug: str, pk: int) -> HttpResponse:
        form = TicketTypeForm(self.request.POST)
        if not form.is_valid():
            return self.render_form(
                slug=slug, form=form, ticket_type=self._read(slug=slug, pk=pk)
            )
        current_event = self.require_current_event(slug)
        try:
            self.request.services.ticket_panel.update_type(
                event_id=current_event.pk, pk=pk, data=_data(form)
            )
        except NotFoundError as exc:
            raise _not_found(slug) from exc
        logger.info(
            "Ticket type updated: event=%s type=%s by=%s",
            current_event.pk,
            pk,
            self.request.context.current_user_id,
        )
        messages.success(self.request, _("Ticket type saved."))
        return redirect(_TICKETS_URL, slug=slug)

    def _read(self, *, slug: str, pk: int) -> TicketTypeDTO:
        current_event = self.require_current_event(slug)
        try:
            return self.request.services.ticket_panel.read_type(
                event_id=current_event.pk, pk=pk
            )
        except NotFoundError as exc:
            raise _not_found(slug) from exc


class _ArchiveActionView(EventPanelAccessMixin, TicketsViewMixin, View):
    request: EventPanelRequest
    http_method_names = ("post",)
    archived: bool

    def post(self, _request: EventPanelRequest, slug: str, pk: int) -> HttpResponse:
        current_event = self.require_current_event(slug)
        try:
            self.request.services.ticket_panel.set_archived(
                event_id=current_event.pk, pk=pk, archived=self.archived
            )
        except NotFoundError as exc:
            raise _not_found(slug) from exc
        logger.info(
            "Ticket type %s: event=%s type=%s by=%s",
            "archived" if self.archived else "restored",
            current_event.pk,
            pk,
            self.request.context.current_user_id,
        )
        messages.success(
            self.request,
            (
                _("Ticket type taken off sale. Tickets already sold stay valid.")
                if self.archived
                else _("Ticket type is back on sale.")
            ),
        )
        return redirect(_TICKETS_URL, slug=slug)


class TicketTypeArchiveActionView(_ArchiveActionView):
    archived = True


class TicketTypeRestoreActionView(_ArchiveActionView):
    archived = False


class TicketOrderRefundActionView(EventPanelAccessMixin, TicketsViewMixin, View):
    request: EventPanelRequest
    http_method_names = ("post",)

    def post(self, _request: EventPanelRequest, slug: str, pk: int) -> HttpResponse:
        current_event = self.require_current_event(slug)
        try:
            outcome = self.request.services.ticket_panel.refund(
                event_id=current_event.pk, order_pk=pk
            )
        except NotFoundError as exc:
            raise RedirectError(
                reverse(_TICKETS_URL, kwargs={"slug": slug}),
                error=_("Order not found."),
            ) from exc
        logger.info(
            "Ticket refund: event=%s order=%s outcome=%s by=%s",
            current_event.pk,
            pk,
            outcome,
            self.request.context.current_user_id,
        )
        match outcome:
            case RefundOutcome.REFUNDED:
                messages.success(
                    self.request,
                    _(
                        "Order refunded. The buyer gets the money back in 5–10 days"
                        " and the tickets no longer admit anyone."
                    ),
                )
            case RefundOutcome.NOT_REFUNDABLE:
                messages.error(self.request, _("Only a paid order can be refunded."))
            case RefundOutcome.PROVIDER_ERROR:
                messages.error(
                    self.request,
                    _(
                        "Stripe didn't accept the refund. Try again, or refund the"
                        " payment from your Stripe dashboard."
                    ),
                )
            case _:
                assert_never(outcome)
        return redirect(_TICKETS_URL, slug=slug)
