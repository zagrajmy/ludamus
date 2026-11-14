from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from django.template import Context, Template
from django.utils import translation
from freezegun import freeze_time

from ludamus.gates.web.django.templatetags.date_tags import format_datetime_range

WARSAW = ZoneInfo("Europe/Warsaw")
FRIDAY = datetime(2026, 9, 4, 16, 0, tzinfo=WARSAW)


@dataclass
class _Range:
    start_time: datetime
    end_time: datetime


def test_short_date_reads_the_same_clock_as_the_time_filter() -> None:
    # The two are printed side by side ("Sat Sep 5 at 0:30"), and Django only
    # moves a datetime into the active zone for a filter that says it expects
    # local time. Without that the day came from UTC and the hour from the
    # site's zone, so a window opening just after local midnight was announced
    # on the day before.
    just_before_midnight_utc = datetime(2026, 9, 4, 22, 30, tzinfo=UTC)
    template = Template(
        '{% load date_tags %}{{ when|short_date }} {{ when|time:"G:i" }}'
    )

    with translation.override("en"):
        rendered = template.render(Context({"when": just_before_midnight_utc}))

    assert rendered == "Sat Sep 5 0:30"


@freeze_time("2026-06-01")
def test_format_datetime_range_names_one_day_once() -> None:
    one_day = _Range(FRIDAY, datetime(2026, 9, 4, 19, 0, tzinfo=WARSAW))

    with translation.override("pl"):
        assert format_datetime_range(one_day) == "4 wrz, 16:00 – 19:00"


@freeze_time("2026-06-01")
def test_format_datetime_range_dates_each_hour_of_a_multi_day_event() -> None:
    weekend = _Range(FRIDAY, datetime(2026, 9, 6, 17, 0, tzinfo=WARSAW))

    with translation.override("pl"):
        assert format_datetime_range(weekend) == "4 wrz, 16:00 – 6 wrz, 17:00"


@freeze_time("2025-06-01")
def test_format_datetime_range_adds_the_year_outside_the_current_one() -> None:
    weekend = _Range(FRIDAY, datetime(2026, 9, 6, 17, 0, tzinfo=WARSAW))

    with translation.override("pl"):
        assert format_datetime_range(weekend) == "4 wrz 2026, 16:00 – 6 wrz 2026, 17:00"


@freeze_time("2026-06-01")
def test_format_datetime_range_dates_both_sides_of_a_new_year() -> None:
    new_year = _Range(
        datetime(2026, 12, 30, 20, 0, tzinfo=WARSAW),
        datetime(2027, 1, 2, 4, 0, tzinfo=WARSAW),
    )

    with translation.override("pl"):
        assert (
            format_datetime_range(new_year) == "30 gru 2026, 20:00 – 2 sty 2027, 04:00"
        )
