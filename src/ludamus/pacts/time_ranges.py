"""The one overlap rule for half-open [start, end) spans."""

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import datetime


class DateTimeRangeProtocol(Protocol):
    """Protocol for objects with start_time and end_time datetime fields."""

    start_time: datetime
    end_time: datetime


def overlaps(*, span: DateTimeRangeProtocol, start: datetime, end: datetime) -> bool:
    # Touching ends do not overlap: a slot ending at 12:00 and one starting at
    # 12:00 share no instant.
    return span.start_time < end and span.end_time > start
