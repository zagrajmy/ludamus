# The sphere's one feed: announcements, then what is coming up — published
# events and the encounters this visitor may see, merged chronologically —
# then what has been. Pure presentation; the merge lives here, not in a mill.
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_control
from django.views.decorators.vary import vary_on_cookie as vary_cookie
from django.views.generic.base import TemplateView

from ludamus.gates.web.django.access import has_panel_access
from ludamus.gates.web.django.chronology.event_presentation import (
    EventInfo,
    split_events,
)

if TYPE_CHECKING:
    from datetime import datetime

    from ludamus.gates.web.django.entities import RootRequest
    from ludamus.pacts import EncounterIndexItem


# Two shapes rather than one with a discriminator and two Nones: a feed entry
# is either an event or an encounter, never both and never neither. `kind` is
# a ClassVar so the template keeps one way to branch and no caller can set it
# against the payload it ships with.
@dataclass(frozen=True)
class FeedEvent:
    start_time: datetime
    event: EventInfo
    kind: ClassVar[Literal["event"]] = "event"


@dataclass(frozen=True)
class FeedEncounter:
    start_time: datetime
    encounter: EncounterIndexItem
    kind: ClassVar[Literal["encounter"]] = "encounter"


type FeedItem = FeedEvent | FeedEncounter


def _merge(
    events: list[EventInfo], encounters: list[EncounterIndexItem], *, newest_first: bool
) -> list[FeedItem]:
    items: list[FeedItem] = [
        FeedEvent(start_time=event.start_time, event=event) for event in events
    ] + [
        FeedEncounter(start_time=item.encounter.start_time, encounter=item)
        for item in encounters
    ]
    items.sort(key=lambda item: item.start_time, reverse=newest_first)
    return items


@method_decorator([cache_control(private=True, max_age=180), vary_cookie], name="get")
class EventsPageView(TemplateView):
    request: RootRequest
    template_name = "index.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        sphere_id = self.request.context.current_sphere_id
        user_id = self.request.context.current_user_id
        context["announcements"] = self.request.services.announcements.list_published(
            sphere_id
        )
        events = split_events(
            self.request.services.events.list_for_sphere(
                sphere_id, include_unpublished=has_panel_access(self.request)
            )
        )
        # Listed encounters for everyone, plus the ones this visitor organises
        # or holds an RSVP to — the only place either is listed now.
        encounters = self.request.services.encounters.list_feed(
            sphere_id=sphere_id, user_id=user_id
        )
        context["upcoming"] = _merge(
            events.upcoming, encounters.upcoming, newest_first=False
        )
        context["past"] = _merge(events.past, encounters.past, newest_first=True)
        context["can_create_encounter"] = (
            user_id is not None
            and self.request.services.encounters.can_create(
                sphere_id=sphere_id, user_id=user_id
            )
        )
        return context
