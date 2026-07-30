"""Post-schedule confirmation tracking: dashboard and per-block working list."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.views.generic.base import View

from ludamus.gates.web.django.chronology.panel.views.base import (
    EventContextMixin,
    PanelAccessMixin,
    PanelRequest,
)
from ludamus.gates.web.django.chronology.panel.views.timetable import timetable_tab_urls

if TYPE_CHECKING:
    from django.http import HttpResponse


class ConfirmationsPageView(PanelAccessMixin, EventContextMixin, View):
    """Confirmation progress for the event, or for one block once chosen."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        sorted_tracks, managed_pks, filter_track_pk = self.get_track_filter_context(
            current_event.pk
        )

        context["active_nav"] = "timetable"
        context["all_tracks"] = sorted_tracks
        context["managed_track_pks"] = managed_pks
        context["filter_track_pk"] = filter_track_pk
        # No block chosen: the event-wide dashboard answers "where do I start".
        # A block chosen: the facilitators of that block, ready to work through.
        context["dashboard"] = (
            None
            if filter_track_pk
            else self.request.services.confirmations.dashboard(current_event.pk)
        )
        context["track_view"] = (
            self.request.services.confirmations.track_view(
                event_pk=current_event.pk, track_pk=filter_track_pk
            )
            if filter_track_pk
            else None
        )
        context["slug"] = slug
        context["tab_urls"] = timetable_tab_urls(slug)
        context["active_tab"] = "confirmations"
        return TemplateResponse(
            self.request, "panel/timetable-confirmations.html", context
        )
