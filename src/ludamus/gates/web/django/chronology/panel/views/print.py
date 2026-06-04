"""Printable materials panel views (print-styled HTML pages).

Served as standalone print pages; the organizer uses the browser's
Save-as-PDF. Rendered in the request's active locale; session titles stay
as authored.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.timezone import get_current_timezone
from django.views.generic.base import View

from ludamus.gates.web.django.chronology.panel.views.base import (
    EventContextMixin,
    PanelAccessMixin,
    PanelRequest,
)

if TYPE_CHECKING:
    from django.http import HttpResponse


class TimetablePrintView(PanelAccessMixin, EventContextMixin, View):
    request: PanelRequest
    material: str = "timetable"

    def get(self, request: PanelRequest, slug: str) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        tz = get_current_timezone()
        service = self.request.services.print_materials

        if self.material == "door-cards":
            return TemplateResponse(
                request,
                "panel/print/door-cards.html",
                {"document": service.build_door_cards(current_event.pk, tz)},
            )
        return TemplateResponse(
            request,
            "panel/print/timetable.html",
            {"document": service.build_timetable(current_event.pk, tz)},
        )
