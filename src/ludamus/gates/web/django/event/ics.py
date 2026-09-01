from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from django.http import Http404, HttpResponse
from django.urls import reverse
from django.utils.cache import patch_cache_control, patch_vary_headers
from django.views.generic.base import View

from ludamus.gates.web.django.access import panel_access
from ludamus.gates.web.django.helpers import is_event_published
from ludamus.gates.web.django.sphere.pages import EventsPageRequiredMixin
from ludamus.mills.calendar import CalendarEntry, ics_document
from ludamus.pacts import NotFoundError

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
        try:
            event = request.services.events.read_by_slug(
                request.context.current_sphere_id, slug
            )
        except NotFoundError as exc:
            raise Http404 from exc
        if not is_event_published(event) and not panel_access(request).granted:
            raise Http404

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
