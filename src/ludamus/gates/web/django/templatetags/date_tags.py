import calendar
from datetime import timedelta
from typing import TYPE_CHECKING, TypedDict

from django import template
from django.utils import timezone
from django.utils.formats import date_format, get_format, time_format
from django.utils.translation import gettext as _

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


def _format_date_range(start: datetime, end: datetime) -> str:
    """Render a range as "4 wrz, 18:00 – 6 wrz, 19:00", dropping a repeated date."""
    # A listing is overwhelmingly about the current year; the events outside it,
    # and any range that crosses a new year, have to say which one.
    spec = _short_spec(
        with_year=start.year != end.year or start.year != timezone.localtime().year
    )
    # Each hour keeps its own date. Collapsing them ("4–6 wrz, 18:00 – 19:00")
    # is shorter but reads as the hours the event runs on each of those days.
    if start.date() == end.date():
        return f"{date_format(start, format=spec)}, {_time(start)} – {_time(end)}"
    return (
        f"{date_format(start, format=spec)}, {_time(start)} – "
        f"{date_format(end, format=spec)}, {_time(end)}"
    )


# Without expects_localtime the filter is handed the raw UTC value while the
# built-in date/time filters beside it get the local one, so the same instant
# can be printed with one day's date and the next day's hour.
@register.filter(expects_localtime=True)
def short_date(value: datetime) -> str:
    return date_format(value, format=f"D {_short_spec(with_year=False)}")


@register.filter
def format_datetime_range(obj: DateTimeRangeProtocol) -> str:
    return _format_date_range(
        timezone.localtime(obj.start_time), timezone.localtime(obj.end_time)
    )


# A game night that runs 19:00–01:00 is one evening on a calendar, not two
# days, so the small hours count towards the day before.
_DAY_ROLLOVER = timedelta(hours=6)


class DateLeaf(TypedDict):
    band: str
    band_is_long: bool
    datetime: str
    day: str
    hour: str
    is_ongoing: bool
    is_range: bool
    is_sunday: bool
    is_today: bool
    label: str
    weekday: str


@register.inclusion_tag("components/date_leaf.html")
def date_leaf(start: datetime, end: datetime | None = None) -> DateLeaf:
    """Lay a start (and optional end) out as a tear-off calendar page.

    Returns:
        The page's lines: the month band, the day or day range, the weekday
        or weekday range and the start hour, plus the flags that colour them.
    """
    start = timezone.localtime(start)
    finish = timezone.localtime(end) if end else start
    first = start.date()
    last = max(first, (finish - _DAY_ROLLOVER).date())
    now = timezone.localtime()
    is_range = last != first
    if (first.year, first.month) == (last.year, last.month):
        band = date_format(first, format="b")
        # Past items reach back past New Year, where "paź" alone is ambiguous.
        if first.year != now.year:
            band = f"{band} {first.year}"
    else:
        # NOTE: a range across New Year has no room for a year on a 58 px
        # page; its months already say which way it runs.
        band = f"{date_format(first, format='b')}–{date_format(last, format='b')}"
    if is_range:
        day = f"{first.day}–{last.day}"
        weekday = f"{date_format(first, format='D')}–{date_format(last, format='D')}"
    else:
        day = str(first.day)
        weekday = date_format(first, format="D")
    label = (
        _format_date_range(start, finish)
        if end
        else f"{date_format(start, format=_short_spec(with_year=True))}, {_time(start)}"
    )
    is_today = not is_range and first == now.date()
    is_ongoing = is_range and start <= now <= finish
    return {
        "band": band,
        "band_is_long": len(band) > len("paź"),
        "datetime": start.isoformat(),
        "day": day,
        # A 58 px page has no room for "12:30 p.m.", so the page itself keeps
        # to the 24-hour clock; the spoken label follows the locale.
        "hour": _("ongoing") if is_ongoing else date_format(start, format="H:i"),
        "is_ongoing": is_ongoing,
        "is_range": is_range,
        "is_sunday": not is_range and first.weekday() == calendar.SUNDAY,
        "is_today": is_today,
        "label": label,
        "weekday": _("today") if is_today else weekday,
    }
