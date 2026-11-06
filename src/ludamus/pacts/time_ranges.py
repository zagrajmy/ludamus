"""The one overlap rule for half-open [start, end) spans."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from ludamus.pacts.legacy import DateTimeRangeProtocol


def overlaps(*, span: DateTimeRangeProtocol, start: datetime, end: datetime) -> bool:
    # Touching ends do not overlap: a slot ending at 12:00 and one starting at
    # 12:00 share no instant.
    return span.start_time < end and span.end_time > start
