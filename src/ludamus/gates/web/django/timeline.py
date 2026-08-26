# The unified homepage feed: published events and public encounters merged
# chronologically. Pure presentation — the merge lives here, not in a mill.
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from django.views.generic.base import TemplateView

from ludamus.gates.web.django.chronology.event_presentation import (
    EventInfo,
    with_covers,
)
from ludamus.gates.web.django.sphere.pages import SpherePageRequiredMixin
from ludamus.pacts import SpherePage

if TYPE_CHECKING:
    from datetime import datetime

    from ludamus.gates.web.django.entities import RootRequest
    from ludamus.pacts import EncounterIndexItem


@dataclass(frozen=True)
class TimelineItem:
    kind: Literal["event", "encounter"]
    start_time: datetime
    event: EventInfo | None = None
    encounter: EncounterIndexItem | None = None


class TimelinePageView(SpherePageRequiredMixin, TemplateView):
    request: RootRequest
    template_name = "timeline.html"
    required_sphere_page = SpherePage.TIMELINE

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        sphere_id = self.request.context.current_sphere_id
        events = self.request.services.events.list_for_sphere(
            sphere_id, include_unpublished=False
        )
        # user_id=None on purpose: the timeline is the same public feed for
        # everyone; the personal split lives on the encounters page.
        encounters = self.request.services.encounters.build_index(
            sphere_id=sphere_id, user_id=None
        ).public

        upcoming = [
            TimelineItem(kind="event", start_time=event.start_time, event=event)
            for event in with_covers([e for e in events if not e.is_ended])
        ] + [
            TimelineItem(
                kind="encounter", start_time=item.encounter.start_time, encounter=item
            )
            for item in encounters
        ]
        upcoming.sort(key=lambda item: item.start_time)
        context["timeline_upcoming"] = upcoming
        context["timeline_past"] = [
            TimelineItem(kind="event", start_time=event.start_time, event=event)
            for event in with_covers(
                sorted(
                    (e for e in events if e.is_ended),
                    key=lambda e: e.start_time,
                    reverse=True,
                )
            )
        ]
        return context
