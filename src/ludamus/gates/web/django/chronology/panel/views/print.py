"""Printable materials panel views (PDF door cards and timetable)."""

from __future__ import annotations

from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils.timezone import get_current_timezone
from django.views.generic.base import View

from ludamus.gates.web.django.chronology.panel.views.base import (
    EventContextMixin,
    PanelAccessMixin,
    PanelRequest,
)
from ludamus.gates.web.django.pdf import render_template_to_pdf


class TimetablePrintView(PanelAccessMixin, EventContextMixin, View):
    """Stream a printable PDF of the event's scheduled program.

    Renders in the request's active locale; session titles stay as authored.
    """

    request: PanelRequest
    material: str = "timetable"

    def get(self, request: PanelRequest, slug: str) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        tz = get_current_timezone()
        service = self.request.services.print_materials
        base_url = request.build_absolute_uri("/")

        if self.material == "door-cards":
            pdf = render_template_to_pdf(
                "panel/print/door-cards.html",
                {"document": service.build_door_cards(current_event.pk, tz)},
                base_url=base_url,
            )
            filename = f"{current_event.slug}-door-cards.pdf"
        else:
            pdf = render_template_to_pdf(
                "panel/print/timetable.html",
                {"document": service.build_timetable(current_event.pk, tz)},
                base_url=base_url,
            )
            filename = f"{current_event.slug}-timetable.pdf"

        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
