"""Printable materials panel views (print-styled HTML pages).

Served as standalone print pages; the organizer prints via the browser
(Save-as-PDF or Ctrl/Cmd+P). Rendered in the request's active locale;
session titles stay as authored. An optional ``?venue=<slug>`` (and
``&area=<slug>``) scopes the document to one venue or area.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.timezone import get_current_timezone
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.chronology.panel.views.base import (
    EventContextMixin,
    PanelAccessMixin,
    PanelRequest,
)
from ludamus.pacts import NotFoundError

if TYPE_CHECKING:
    from django.http import HttpResponse


class TimetablePrintView(PanelAccessMixin, EventContextMixin, View):
    request: PanelRequest
    material: str = "timetable"

    def get(self, request: PanelRequest, slug: str) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        try:
            scope = self.request.services.venues.resolve_scope(
                current_event.pk,
                self.request.GET.get("venue") or None,
                self.request.GET.get("area") or None,
            )
        except NotFoundError:
            messages.error(request, _("Venue or area not found."))
            return redirect("panel:timetable", slug=slug)

        tz = get_current_timezone()
        service = self.request.services.print_materials

        if self.material == "door-cards":
            return TemplateResponse(
                request,
                "panel/print/door-cards.html",
                {
                    "document": service.build_door_cards(
                        current_event.pk,
                        tz,
                        area_pks=scope.area_pks,
                        scope_name=scope.scope_name,
                    )
                },
            )
        return TemplateResponse(
            request,
            "panel/print/timetable.html",
            {
                "document": service.build_timetable(
                    current_event.pk,
                    tz,
                    area_pks=scope.area_pks,
                    scope_name=scope.scope_name,
                )
            },
        )


class PrintMaterialsPageView(PanelAccessMixin, EventContextMixin, View):
    """Hub page linking to the printable materials for an event."""

    request: PanelRequest

    def get(self, request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        context["active_nav"] = "print"
        context["print_venues"] = self.get_print_venues(current_event.pk)
        return TemplateResponse(request, "panel/print-materials.html", context)
