from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from ludamus.mills.timeslots import (
    interval_windows,
    local_date,
    programme_date,
    programme_day_start,
    programme_windows,
)

_TZ = ZoneInfo("Europe/Warsaw")


class TestIntervalWindows:
    def test_same_day_stays_one_window(self):
        start = datetime(2026, 7, 10, 12, tzinfo=_TZ)
        end = datetime(2026, 7, 10, 14, tzinfo=_TZ)

        assert interval_windows(start=start, end=end, tz=_TZ) == [(start, end)]

    def test_night_interval_splits_at_local_midnight(self):
        start = datetime(2026, 7, 10, 22, tzinfo=_TZ)
        end = datetime(2026, 7, 11, 2, tzinfo=_TZ)
        midnight = datetime(2026, 7, 11, 0, tzinfo=_TZ)

        assert interval_windows(start=start, end=end, tz=_TZ) == [
            (start, midnight),
            (midnight, end),
        ]

    def test_repeated_hour_is_compared_as_real_instants(self):
        start = datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
        end = datetime(2026, 10, 25, 1, 15, tzinfo=UTC)

        assert interval_windows(start=start, end=end, tz=_TZ) == [
            (start.astimezone(_TZ), end.astimezone(_TZ))
        ]

    def test_converts_from_utc_into_tz(self):
        start = datetime(2026, 7, 10, 20, tzinfo=UTC)
        end = datetime(2026, 7, 10, 23, tzinfo=UTC)

        assert interval_windows(start=start, end=end, tz=_TZ) == [
            (
                datetime(2026, 7, 10, 22, tzinfo=_TZ),
                datetime(2026, 7, 11, 0, tzinfo=_TZ),
            ),
            (
                datetime(2026, 7, 11, 0, tzinfo=_TZ),
                datetime(2026, 7, 11, 1, tzinfo=_TZ),
            ),
        ]


class TestProgrammeDays:
    def test_a_night_session_stays_on_the_evening_it_belongs_to(self):
        start = datetime(2026, 7, 10, 22, tzinfo=_TZ)
        end = datetime(2026, 7, 11, 2, tzinfo=_TZ)

        assert programme_windows(start=start, end=end, tz=_TZ) == [(start, end)]
        assert programme_date(end, _TZ) == date(2026, 7, 10)

    def test_a_session_through_the_turnover_splits_there(self):
        start = datetime(2026, 7, 11, 4, tzinfo=_TZ)
        end = datetime(2026, 7, 11, 8, tzinfo=_TZ)
        turnover = datetime(2026, 7, 11, 6, tzinfo=_TZ)

        assert programme_windows(start=start, end=end, tz=_TZ) == [
            (start, turnover),
            (turnover, end),
        ]

    def test_the_day_opens_at_the_turnover(self):
        assert programme_day_start(date(2026, 7, 11), _TZ) == datetime(
            2026, 7, 11, 6, tzinfo=_TZ
        )

    def test_a_day_turning_at_a_half_hour_is_honoured(self):
        instant = datetime(2026, 7, 11, 5, 45, tzinfo=_TZ)

        assert local_date(instant, tz=_TZ, day_starts_at=time(5, 30)) == date(
            2026, 7, 11
        )
        assert local_date(instant, tz=_TZ, day_starts_at=time(6)) == date(2026, 7, 10)
