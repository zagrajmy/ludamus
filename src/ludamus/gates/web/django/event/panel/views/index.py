"""Panel index/dashboard views."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.views.generic.base import View

from ludamus.gates.web.django.event.panel.views.base import EventPanelMixin
from ludamus.gates.web.django.panel import PanelAccessMixin, PanelRequest

if TYPE_CHECKING:
    from django.http import HttpResponse


class PanelIndexRedirectView(PanelAccessMixin, View):
    """Redirect /panel/ to first event's index page."""

    request: PanelRequest

    # _request: dispatch requires it but we use self.request instead
    def get(self, _request: PanelRequest) -> HttpResponse:
        """Redirect to first event's panel page.

        Returns:
            Redirect to the first event, or to event creation when there is none.
        """
        sphere_id = self.request.context.current_sphere_id

        if not (events := self.request.services.sphere_panel.list_events(sphere_id)):
            return redirect("panel:event-create")

        return redirect("panel:event-index", slug=events[0].slug)


class EventIndexPageView(EventPanelMixin, View):
    """Dashboard/index page for a specific event."""

    request: PanelRequest

    def get(self, _request: PanelRequest, **_kwargs: str) -> HttpResponse:
        """Display dashboard for a specific event.

        Returns:
            TemplateResponse with the dashboard or redirect if event not found.
        """
        context = self.panel_context()

        context["active_nav"] = "index"
        return TemplateResponse(self.request, "panel/index.html", context)
