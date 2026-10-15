from typing import TYPE_CHECKING

from django import template
from django.utils import timezone

from ludamus.gates.web.django.helpers import placeholder_cover_url

if TYPE_CHECKING:
    from datetime import datetime

register = template.Library()


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
