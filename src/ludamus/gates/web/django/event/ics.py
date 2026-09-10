from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from django.http import HttpResponse
from django.urls import reverse
from django.utils.cache import patch_cache_control, patch_vary_headers
from django.views.generic.base import View

from ludamus.gates.web.django.helpers import read_public_event
from ludamus.gates.web.django.sphere.pages import EventsPageRequiredMixin
from ludamus.mills.calendar import CalendarEntry, ics_document

if TYPE_CHECKING:
    from ludamus.gates.web.django.entities import RootRequest
    from ludamus.pacts import EventDTO


def event_calendar_entry(event: EventDTO, *, request: RootRequest) -> CalendarEntry:
    """One description of an event, so its .ics and its links cannot drift."""
    return CalendarEntry(
        uid=f"event-{event.pk}@{request.get_host()}",
        title=event.name,
        start=event.start_time,
        end=event.end_time,
        url=request.build_absolute_uri(
            reverse("web:chronology:event", kwargs={"slug": event.slug})
        ),
        location=event.address_inline,
    )


class EventICSView(EventsPageRequiredMixin, View):
    """Single-VEVENT calendar file for one event ("Other calendars" download)."""

    @staticmethod
    def get(request: RootRequest, slug: str) -> HttpResponse:
        event = read_public_event(request, slug)

        entry = event_calendar_entry(event, request=request)
        response = HttpResponse(
            ics_document(entry, stamped_at=datetime.now(tz=UTC)),
            content_type="text/calendar; charset=utf-8",
        )
        response["Content-Disposition"] = f'attachment; filename="{event.slug}.ics"'
        # An unpublished event answers only to panel access, so the file is
        # per-reader, never shared-cacheable.
        patch_cache_control(response, private=True, max_age=180)
        patch_vary_headers(response, ["Cookie"])
        return response
