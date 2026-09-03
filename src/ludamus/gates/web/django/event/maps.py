"""Public maps page: every venue plan of an event, each listing its spaces."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.http import Http404
from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.generic.base import View

from ludamus.gates.web.django.access import panel_access
from ludamus.gates.web.django.helpers import is_event_published
from ludamus.gates.web.django.sphere.pages import EventsPageRequiredMixin
from ludamus.pacts import NotFoundError

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.gates.web.django.entities import RootRequest


class EventMapsPageView(EventsPageRequiredMixin, View):
    request: RootRequest

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

        return TemplateResponse(
            request,
            "chronology/maps.html",
            {
                "event": event,
                "maps": request.services.event_maps.list_for_event(event.pk),
                "schedule_url": reverse(
                    "web:chronology:event", kwargs={"slug": event.slug}
                ),
            },
        )
