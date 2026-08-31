from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from django.http import Http404, HttpResponse
from django.urls import reverse
from django.utils.cache import patch_cache_control, patch_vary_headers
from django.views.generic.base import View

from ludamus.gates.web.django.access import panel_access
from ludamus.gates.web.django.helpers import is_event_published
from ludamus.pacts import NotFoundError

if TYPE_CHECKING:
    from ludamus.gates.web.django.entities import RootRequest


def ics_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def ics_utc(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


class EventICSView(View):
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

        event_url = request.build_absolute_uri(
            reverse("web:chronology:event", kwargs={"slug": slug})
        )
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Zagrajmy//Event//PL",
            "BEGIN:VEVENT",
            f"UID:event-{event.pk}@{request.get_host()}",
            f"DTSTAMP:{ics_utc(datetime.now(tz=UTC))}",
            f"DTSTART:{ics_utc(event.start_time)}",
            f"DTEND:{ics_utc(event.end_time)}",
            f"SUMMARY:{ics_escape(event.name)}",
            f"URL:{event_url}",
        ]
        if event.address:
            lines.append(f"LOCATION:{ics_escape(event.address_inline)}")
        lines += ["END:VEVENT", "END:VCALENDAR"]
        response = HttpResponse(
            "\r\n".join(lines) + "\r\n", content_type="text/calendar; charset=utf-8"
        )
        response["Content-Disposition"] = f'attachment; filename="{event.slug}.ics"'
        patch_cache_control(response, private=True, max_age=180)
        patch_vary_headers(response, ["Cookie"])
        return response
