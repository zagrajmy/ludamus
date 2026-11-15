from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.pacts.event import EventVisibility, PublicationChoice

if TYPE_CHECKING:
    from datetime import datetime

    from ludamus.pacts.event import EventDTO, PublicationIntent


def resolve_publication(
    *, intent: PublicationIntent, event: EventDTO, start_time: datetime, now: datetime
) -> tuple[EventVisibility, datetime | None]:
    """Turn an organizer's visibility choice into what the event stores.

    Only SCHEDULED shows its time on the form. The other two keep or pick a
    time the organizer never sees, so it is held to the start the event is
    saved with: a publication after the start is refused, and a refusal on a
    hidden field would leave the form unsaved with no visible reason.

    An event already out keeps its publication time: errata are listed from
    it, so moving it to now would drop every change made since it went out.

    Returns:
        The visibility and publication time to store.
    """
    if intent.choice is PublicationChoice.SCHEDULED:
        return EventVisibility.PUBLIC, intent.chosen_time
    stored = event.publication_time
    if intent.choice is PublicationChoice.LINK_ONLY:
        kept = None if stored is None else min(stored, start_time)
        return EventVisibility.UNLISTED, kept
    if event.is_published and stored is not None:
        return EventVisibility.PUBLIC, min(stored, start_time)
    return EventVisibility.PUBLIC, min(now, start_time)
