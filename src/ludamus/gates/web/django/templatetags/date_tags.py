from typing import TYPE_CHECKING

from django import template
from django.utils import timezone
from django.utils.formats import date_format, get_format, time_format

if TYPE_CHECKING:
    from datetime import datetime

    from ludamus.pacts import DateTimeRangeProtocol

register = template.Library()

# Django writes the long month as "F"/"N", or "E" where the locale declines it;
# "M"/"b" are the matching abbreviations. Swapping the token inside the locale's
# own format keeps everything else the locale decided — day/month order, the
# comma before the year, and the case Polish wants: "F j" → "M j" (Sep 4),
# "j E Y" → "j b Y" (4 wrz 2026).
_ABBREVIATED_MONTH = str.maketrans({"F": "M", "N": "M", "E": "b"})


def _short_spec(*, with_year: bool) -> str:
    # get_format is typed Any because some format keys hold lists; these two
    # are format strings.
    spec: str = get_format("DATE_FORMAT" if with_year else "MONTH_DAY_FORMAT")
    return spec.translate(_ABBREVIATED_MONTH)


def _time(value: datetime) -> str:
    return time_format(value, format="TIME_FORMAT", use_l10n=True)


def _collapsed_days(*, start: datetime, end: datetime, spec: str) -> str:
    # Two days of one month print as a single date carrying a day range, on
    # whichever side of the month the locale puts the day: "Sep 4–6", "4–6 wrz".
    day = "j" if "j" in spec else "d"
    head, _, tail = spec.partition(day)
    days = f"{date_format(start, format=day)}–{date_format(end, format=day)}"
    # An empty spec makes date_format fall back to DATE_FORMAT, so each side is
    # rendered only where the locale put something.
    left = date_format(start, format=head) if head else ""
    right = date_format(end, format=tail) if tail else ""
    return f"{left}{days}{right}"


def _format_date_range(start: datetime, end: datetime) -> str:
    """Render a range as "4–6 wrz, 18:00 – 19:00", collapsing what repeats."""
    # A listing is overwhelmingly about the current year; the events outside it,
    # and any range that crosses a new year, have to say which one.
    spec = _short_spec(
        with_year=start.year != end.year or start.year != timezone.localtime().year
    )

    if start.date() == end.date():
        dates = date_format(start, format=spec)
    elif (start.year, start.month) == (end.year, end.month):
        dates = _collapsed_days(start=start, end=end, spec=spec)
    else:
        dates = f"{date_format(start, format=spec)} – {date_format(end, format=spec)}"
    return f"{dates}, {_time(start)} – {_time(end)}"


@register.filter
def short_date(value: datetime) -> str:
    return date_format(value, format=f"D {_short_spec(with_year=False)}")


@register.filter
def format_datetime_range(obj: DateTimeRangeProtocol) -> str:
    return _format_date_range(
        timezone.localtime(obj.start_time), timezone.localtime(obj.end_time)
    )
