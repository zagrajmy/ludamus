# The sphere's one feed: announcements, then what is coming up — published
# events and the encounters this visitor may see, merged chronologically —
# then what has been. Pure presentation; the merge lives here, not in a mill.
from __future__ import annotations

from dataclasses import dataclass
from operator import attrgetter
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
from ludamus.pacts.encounter import PAST_FEED_LIMIT

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
    entry: EventInfo
    kind: ClassVar[Literal["event"]] = "event"

    @property
    def start_time(self) -> datetime:
        return self.entry.start_time


@dataclass(frozen=True)
class FeedEncounter:
    entry: EncounterIndexItem
    kind: ClassVar[Literal["encounter"]] = "encounter"

    @property
    def start_time(self) -> datetime:
        return self.entry.encounter.start_time


type FeedItem = FeedEvent | FeedEncounter


def _merge(
    *, events: list[EventInfo], encounters: list[EncounterIndexItem], newest_first: bool
) -> list[FeedItem]:
    merged: list[FeedItem] = [FeedEvent(entry=event) for event in events] + [
        FeedEncounter(entry=item) for item in encounters
    ]
    return sorted(merged, key=attrgetter("start_time"), reverse=newest_first)


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
                sphere_id, include_hidden=has_panel_access(self.request)
            )
        )
        # Listed encounters for everyone, plus the ones this visitor organises
        # or holds an RSVP to — the only place either is listed now.
        encounters = self.request.services.encounters.list_feed(
            sphere_id=sphere_id, user_id=user_id
        )
        context["upcoming"] = _merge(
            events=events.upcoming, encounters=encounters.upcoming, newest_first=False
        )
        # Cut after the merge, not only in the encounter query: capping one
        # side alone leaves a hole, where an event older than the last
        # encounter shown renders while the encounters between them do not.
        context["past"] = _merge(
            events=events.past, encounters=encounters.past, newest_first=True
        )[:PAST_FEED_LIMIT]
        context["can_create_encounter"] = (
            user_id is not None
            and self.request.services.encounters.can_create(
                sphere_id=sphere_id, user_id=user_id
            )
        )
        return context
