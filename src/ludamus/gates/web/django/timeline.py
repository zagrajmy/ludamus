# The unified homepage feed: published events and public encounters merged
# chronologically. Pure presentation — the merge lives here, not in a mill.
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from django.views.generic.base import TemplateView

from ludamus.gates.web.django.chronology.event_presentation import (
    EventInfo,
    split_events,
)
from ludamus.gates.web.django.sphere.pages import SpherePageRequiredMixin
from ludamus.pacts import SpherePage

if TYPE_CHECKING:
    from datetime import datetime

    from ludamus.gates.web.django.entities import RootRequest
    from ludamus.pacts import EncounterIndexItem


# Two shapes rather than one with a discriminator and two Nones: a timeline
# entry is either an event or an encounter, never both and never neither.
# `kind` is a ClassVar so the templates keep one way to branch and no caller
# can set it against the payload it ships with.
@dataclass(frozen=True)
class TimelineEvent:
    start_time: datetime
    event: EventInfo
    kind: ClassVar[Literal["event"]] = "event"


@dataclass(frozen=True)
class TimelineEncounter:
    start_time: datetime
    encounter: EncounterIndexItem
    kind: ClassVar[Literal["encounter"]] = "encounter"


type TimelineItem = TimelineEvent | TimelineEncounter


class TimelinePageView(SpherePageRequiredMixin, TemplateView):
    request: RootRequest
    template_name = "timeline.html"
    required_sphere_page = SpherePage.TIMELINE

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        sphere_id = self.request.context.current_sphere_id
        events = split_events(
            self.request.services.events.list_for_sphere(
                sphere_id, include_unpublished=False
            )
        )
        # The public feed, not a personal one: the timeline reads the same for
        # everyone; the personal split lives on the encounters page.
        encounters = self.request.services.encounters.list_public_upcoming(
            sphere_id=sphere_id
        )

        upcoming: list[TimelineItem] = [
            TimelineEvent(start_time=event.start_time, event=event)
            for event in events.upcoming
        ] + [
            TimelineEncounter(start_time=item.encounter.start_time, encounter=item)
            for item in encounters
        ]
        upcoming.sort(key=lambda item: item.start_time)
        context["timeline_upcoming"] = upcoming
        # Past entries are events only — an encounter drops off the feed once
        # it starts — so they stay plain events rather than wrapped.
        context["timeline_past"] = events.past
        return context
