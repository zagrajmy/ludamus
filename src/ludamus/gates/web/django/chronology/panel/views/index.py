"""Panel index/dashboard views."""

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


class PanelIndexRedirectView(PanelAccessMixin, View):
    """Redirect /panel/ to first event's index page."""

    request: PanelRequest

    # _request: dispatch requires it but we use self.request instead
    def get(self, _request: PanelRequest) -> HttpResponse:
        """Redirect to first event's panel page.

        Returns:
            Redirect to event-index or web:index if no events.
        """
        sphere_id = self.request.context.current_sphere_id

        if not (events := self.request.services.sphere_panel.list_events(sphere_id)):
            messages.info(self.request, _("No events available for this sphere."))
            return redirect("web:index")

        return redirect("panel:event-index", slug=events[0].slug)


class EventIndexPageView(PanelAccessMixin, EventContextMixin, View):
    """Dashboard/index page for a specific event."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        """Display dashboard for a specific event.

        Returns:
            TemplateResponse with the dashboard or redirect if event not found.
        """
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        context["active_nav"] = "index"
        return TemplateResponse(self.request, "panel/index.html", context)
