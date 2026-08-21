from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from django.utils import translation
from freezegun import freeze_time

from ludamus.gates.web.django.templatetags.date_tags import (
    format_datetime_range,
    short_date,
)

WARSAW = ZoneInfo("Europe/Warsaw")
FRIDAY = datetime(2026, 9, 4, 16, 0, tzinfo=WARSAW)


@dataclass
class _Range:
    start_time: datetime
    end_time: datetime


def test_short_date_leads_with_the_month_in_english() -> None:
    with translation.override("en"):
        assert short_date(FRIDAY) == "Fri Sep 4"


def test_short_date_leads_with_the_day_in_polish() -> None:
    with translation.override("pl"):
        assert short_date(FRIDAY) == "Pt 4 wrz"


@freeze_time("2026-06-01")
def test_format_datetime_range_names_one_day_once() -> None:
    one_day = _Range(FRIDAY, datetime(2026, 9, 4, 19, 0, tzinfo=WARSAW))

    with translation.override("pl"):
        assert format_datetime_range(one_day) == "4 wrz, 16:00 – 19:00"


@freeze_time("2026-06-01")
def test_format_datetime_range_collapses_a_shared_month() -> None:
    weekend = _Range(FRIDAY, datetime(2026, 9, 6, 17, 0, tzinfo=WARSAW))

    with translation.override("pl"):
        assert format_datetime_range(weekend) == "4–6 wrz, 16:00 – 17:00"


@freeze_time("2026-06-01")
def test_format_datetime_range_keeps_the_english_month_first() -> None:
    weekend = _Range(FRIDAY, datetime(2026, 9, 6, 17, 0, tzinfo=WARSAW))

    with translation.override("en"):
        assert format_datetime_range(weekend) == "Sep 4–6, 4 p.m. – 5 p.m."


@freeze_time("2026-06-01")
def test_format_datetime_range_names_both_months_across_a_month_boundary() -> None:
    turn_of_month = _Range(
        datetime(2026, 9, 28, 16, 0, tzinfo=WARSAW),
        datetime(2026, 10, 2, 17, 0, tzinfo=WARSAW),
    )

    with translation.override("pl"):
        assert format_datetime_range(turn_of_month) == "28 wrz – 2 paź, 16:00 – 17:00"


@freeze_time("2025-06-01")
def test_format_datetime_range_adds_the_year_outside_the_current_one() -> None:
    weekend = _Range(FRIDAY, datetime(2026, 9, 6, 17, 0, tzinfo=WARSAW))

    with translation.override("pl"):
        assert format_datetime_range(weekend) == "4–6 wrz 2026, 16:00 – 17:00"


@freeze_time("2026-06-01")
def test_format_datetime_range_dates_both_sides_of_a_new_year() -> None:
    new_year = _Range(
        datetime(2026, 12, 30, 20, 0, tzinfo=WARSAW),
        datetime(2027, 1, 2, 4, 0, tzinfo=WARSAW),
    )

    with translation.override("pl"):
        assert (
            format_datetime_range(new_year) == "30 gru 2026 – 2 sty 2027, 20:00 – 04:00"
        )
