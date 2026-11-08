from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.event.panel.views.base import EventPanelMixin
from ludamus.pacts.ids import EventBanId, EventId

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.gates.web.django.panel import PanelRequest


class BansPageView(EventPanelMixin, View):
    request: PanelRequest

    def get(self, _request: PanelRequest, **_kwargs: str) -> HttpResponse:
        context = self.panel_context()
        context["active_nav"] = "bans"
        context["bans"] = self.request.services.event_bans.list_for_event(
            self.current_event.pk
        )
        return TemplateResponse(self.request, "panel/bans.html", context)

    def post(self, request: PanelRequest, slug: str) -> HttpResponse:
        identifier = request.POST.get("identifier", "")
        reason = request.POST.get("reason", "")
        if request.services.event_bans.ban(
            event_id=self.current_event.pk, identifier=identifier, reason=reason
        ):
            messages.success(request, _("User banned from the event."))
        else:
            messages.error(request, _("No user found with that username or email."))
        return redirect("panel:bans", slug=slug)


class BanDeleteActionView(EventPanelMixin, View):
    request: PanelRequest

    def post(self, request: PanelRequest, slug: str, pk: int) -> HttpResponse:
        request.services.event_bans.unban(
            event_id=EventId(self.current_event.pk), ban_id=EventBanId(pk)
        )
        messages.success(request, _("Ban removed."))
        return redirect("panel:bans", slug=slug)
