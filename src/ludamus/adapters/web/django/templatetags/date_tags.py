# ruff:file-ignore[ambiguous-unicode-character-string]
from typing import TYPE_CHECKING

from django import template
from django.utils import timezone
from django.utils.formats import date_format, time_format

if TYPE_CHECKING:
    from datetime import datetime

    from ludamus.pacts import DateTimeRangeProtocol

register = template.Library()


def _format_date_range(start: datetime, end: datetime) -> str:
    start_date = start.date()
    end_date = end.date()

    if start_date == end_date:
        return (
            f"{date_format(start, format='DATE_FORMAT', use_l10n=True)}, "
            f"{time_format(start, format='TIME_FORMAT', use_l10n=True)} - "
            f"{time_format(end, format='TIME_FORMAT', use_l10n=True)}"
        )

    if start_date.year == end_date.year:
        if start_date.month == end_date.month:
            return (
                f"{date_format(start, 'M j', use_l10n=True)}–"
                f"{date_format(end, 'j, Y', use_l10n=False)}, "
                f"{time_format(start, 'TIME_FORMAT')} – "
                f"{time_format(end, 'TIME_FORMAT')}"
            )
        start_month = date_format(start, format="M", use_l10n=True)
        end_month = date_format(end, format="M", use_l10n=True)
        start_day = date_format(start, format="j", use_l10n=False)
        end_day = date_format(end, format="j", use_l10n=False)
        year = date_format(start, format="Y", use_l10n=False)
        start_time = time_format(start, format="TIME_FORMAT", use_l10n=True)
        end_time = time_format(end, format="TIME_FORMAT", use_l10n=True)
        return (
            f"{start_month} {start_day} - {end_month} {end_day}, {year}, "
            f"{start_time} - {end_time}"
        )
    start_time = time_format(start, format="TIME_FORMAT", use_l10n=True)
    end_time = time_format(end, format="TIME_FORMAT", use_l10n=True)
    return (
        f"{date_format(start, format='DATE_FORMAT', use_l10n=True)}, {start_time} - "
        f"{date_format(end, format='DATE_FORMAT', use_l10n=True)}, {end_time}"
    )


@register.filter
def format_datetime_range(obj: DateTimeRangeProtocol) -> str:
    start = timezone.localtime(obj.start_time)
    end = timezone.localtime(obj.end_time)

    result = _format_date_range(start, end)

    # if year is current, we don't need to show it
    if start.year == timezone.now().year:
        return result.replace(f"{start.year},", "")

    return result
