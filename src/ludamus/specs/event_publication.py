from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.pacts.event import EventVisibility, PublicationChoice

if TYPE_CHECKING:
    from datetime import datetime

    from ludamus.pacts.event import PublicationIntent


def resolve_publication(
    *,
    intent: PublicationIntent,
    stored: datetime | None,
    start_time: datetime,
    now: datetime,
) -> tuple[EventVisibility, datetime | None]:
    """Turn an organizer's visibility choice into what the event stores.

    Only SCHEDULED shows its time on the form. The other two keep or pick a
    time the organizer never sees, so it is held to the start the event is
    saved with: a publication after the start is refused, and a refusal on a
    hidden field would leave the form unsaved with no visible reason.

    Followers are announced to at the publication time, so an event already
    out keeps its time rather than being announced again.

    Returns:
        The visibility and publication time to store.
    """
    if intent.choice is PublicationChoice.SCHEDULED:
        return EventVisibility.PUBLIC, intent.chosen_time
    if intent.choice is PublicationChoice.LINK_ONLY:
        kept = None if stored is None else min(stored, start_time)
        return EventVisibility.UNLISTED, kept
    if stored is not None and stored <= now:
        return EventVisibility.PUBLIC, min(stored, start_time)
    return EventVisibility.PUBLIC, min(now, start_time)
