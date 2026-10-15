from dataclasses import dataclass
from itertools import groupby
from typing import TYPE_CHECKING

from django import template
from django.utils import timezone

from ludamus.gates.web.django.helpers import placeholder_cover_url

if TYPE_CHECKING:
    from datetime import date, datetime

    from ludamus.gates.web.django.events import FeedItem

register = template.Library()

# Up to this many past items read best as cards: three full rows of the
# desktop grid. Past that, people come back to look one up, not to browse.
PAST_CARDS_LIMIT = 9
# The archive opens on its latest months; older ones sit behind a fold.
PAST_OPEN_MONTHS = 3


# The calendar page is pinned to the cover, so a feed card without one would
# have nothing to hang it on; events already fall back the same way.
@register.filter
def cover_or_placeholder(url: str, key: int) -> str:
    return url or placeholder_cover_url(key)


@register.filter
def spots_left(capacity: int, taken: int) -> int:
    return max(capacity - taken, 0)


# Free spots stop meaning anything once it has begun; the card counts who
# came instead.
@register.filter(expects_localtime=True)
def has_started(value: datetime) -> bool:
    return value <= timezone.localtime()


@dataclass(frozen=True)
class PastMonth:
    month: date
    items: list[FeedItem]


@dataclass(frozen=True)
class PastArchive:
    recent: list[PastMonth]
    older: list[PastMonth]

    @property
    def older_count(self) -> int:
        return sum(len(month.items) for month in self.older)


@register.filter
def reads_as_archive(items: list[FeedItem]) -> bool:
    return len(items) > PAST_CARDS_LIMIT


def _month(item: FeedItem) -> date:
    return timezone.localtime(item.start_time).date().replace(day=1)


@register.filter
def past_archive(items: list[FeedItem]) -> PastArchive:
    """Group past items, newest first, into the months they happened in.

    Returns:
        The latest months to show open and the older ones to fold away.
    """
    months = [
        PastMonth(month=month, items=list(group))
        for month, group in groupby(items, key=_month)
    ]
    return PastArchive(
        recent=months[:PAST_OPEN_MONTHS], older=months[PAST_OPEN_MONTHS:]
    )
