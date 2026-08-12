from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from ludamus.mills.timeslots import interval_windows

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
