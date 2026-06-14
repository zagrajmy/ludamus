"""Event ban panel views (organizer-level hard bans)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.chronology.panel.views.base import (
    EventContextMixin,
    PanelAccessMixin,
    PanelRequest,
)

if TYPE_CHECKING:
    from django.http import HttpResponse


class BansPageView(PanelAccessMixin, EventContextMixin, View):
    """List and add event bans."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")
        context["active_nav"] = "bans"
        context["bans"] = self.request.services.event_bans.list_for_event(
            current_event.pk
        )
        return TemplateResponse(self.request, "panel/bans.html", context)

    def post(self, request: PanelRequest, slug: str) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")
        identifier = request.POST.get("identifier", "")
        reason = request.POST.get("reason", "")
        if request.services.event_bans.ban(
            event_id=current_event.pk, identifier=identifier, reason=reason
        ):
            messages.success(request, _("User banned from the event."))
        else:
            messages.error(request, _("No user found with that username or email."))
        return redirect("panel:bans", slug=slug)


class BanDeleteActionView(PanelAccessMixin, EventContextMixin, View):
    """Remove an event ban."""

    request: PanelRequest

    def post(self, request: PanelRequest, slug: str, pk: int) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")
        request.services.event_bans.unban(event_id=current_event.pk, ban_id=pk)
        messages.success(request, _("Ban removed."))
        return redirect("panel:bans", slug=slug)
