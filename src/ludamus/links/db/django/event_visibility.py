"""Where an event shows up: the one rule every event list applies."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import Q

from ludamus.pacts.legacy import EventVisibility

if TYPE_CHECKING:
    from datetime import datetime


def listed_events(*, now: datetime, prefix: str = "") -> Q:
    # Where an event shows up without its link — sphere and landing lists,
    # the dashboard, subscriber announcements. `prefix` reaches it through a
    # relation (`"events__"`). An unlisted event never qualifies.
    return Q(
        **{
            f"{prefix}publication_time__isnull": False,
            f"{prefix}publication_time__lte": now,
            f"{prefix}visibility": EventVisibility.PUBLIC,
        }
    )
