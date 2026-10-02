from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from ludamus.mills.timeslots import MIDNIGHT, PROGRAMME_DAYS, slot_windows_by_local_date
from ludamus.pacts import TimeSlotDTO

_TZ = ZoneInfo("Europe/Warsaw")


class TestMidnightWindows:
    def test_night_interval_splits_at_local_midnight(self):
        start = datetime(2026, 7, 10, 22, tzinfo=_TZ)
        end = datetime(2026, 7, 11, 2, tzinfo=_TZ)
        midnight = datetime(2026, 7, 11, 0, tzinfo=_TZ)

        assert MIDNIGHT.windows(start=start, end=end, tz=_TZ) == [
            (start, midnight),
            (midnight, end),
        ]

    def test_repeated_hour_is_compared_as_real_instants(self):
        start = datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
        end = datetime(2026, 10, 25, 1, 15, tzinfo=UTC)

        assert MIDNIGHT.windows(start=start, end=end, tz=_TZ) == [
            (start.astimezone(_TZ), end.astimezone(_TZ))
        ]


class TestProgrammeDays:
    def test_a_night_session_stays_on_the_evening_it_belongs_to(self):
        start = datetime(2026, 7, 10, 22, tzinfo=_TZ)
        end = datetime(2026, 7, 11, 2, tzinfo=_TZ)

        assert PROGRAMME_DAYS.windows(start=start, end=end, tz=_TZ) == [(start, end)]
        assert PROGRAMME_DAYS.date_of(end, _TZ) == date(2026, 7, 10)

    def test_a_session_through_the_turnover_splits_there(self):
        start = datetime(2026, 7, 11, 4, tzinfo=_TZ)
        end = datetime(2026, 7, 11, 8, tzinfo=_TZ)
        turnover = datetime(2026, 7, 11, 6, tzinfo=_TZ)

        assert PROGRAMME_DAYS.windows(start=start, end=end, tz=_TZ) == [
            (start, turnover),
            (turnover, end),
        ]

    def test_a_day_holds_the_small_hours_before_it_turns(self):
        instant = datetime(2026, 7, 11, 5, 45, tzinfo=_TZ)

        assert MIDNIGHT.date_of(instant, _TZ) == date(2026, 7, 11)
        assert PROGRAMME_DAYS.date_of(instant, _TZ) == date(2026, 7, 10)

    def test_the_spring_forward_morning_turns_over_on_the_wall_clock(self):
        # The clocks jump from 02:00 to 03:00 that night, so only five hours
        # have elapsed since midnight at 06:30 CEST — but the day is open.
        assert PROGRAMME_DAYS.date_of(
            datetime(2026, 3, 29, 4, 30, tzinfo=UTC), _TZ
        ) == date(2026, 3, 29)
        assert PROGRAMME_DAYS.date_of(
            datetime(2026, 3, 29, 3, 30, tzinfo=UTC), _TZ
        ) == date(2026, 3, 28)

    def test_the_autumn_night_gives_the_evening_an_extra_hour(self):
        # 04:30Z is 05:30 CET after the clocks went back: seven hours since
        # midnight, yet still before the turnover.
        assert PROGRAMME_DAYS.date_of(
            datetime(2026, 10, 25, 4, 30, tzinfo=UTC), _TZ
        ) == date(2026, 10, 24)

    def test_an_empty_or_reversed_interval_yields_no_window(self):
        start = datetime(2026, 7, 10, 12, tzinfo=_TZ)

        assert not MIDNIGHT.windows(start=start, end=start, tz=_TZ)

    def test_an_interval_ending_exactly_at_midnight_gives_the_next_day_nothing(self):
        start = datetime(2026, 7, 10, 22, tzinfo=_TZ)
        midnight = datetime(2026, 7, 11, 0, tzinfo=_TZ)

        assert MIDNIGHT.windows(start=start, end=midnight, tz=_TZ) == [
            (start, midnight)
        ]


class TestSlotWindows:
    def test_groups_split_windows_under_their_local_date(self):
        slot = TimeSlotDTO(
            pk=1,
            start_time=datetime(2026, 7, 10, 22, tzinfo=_TZ),
            end_time=datetime(2026, 7, 11, 2, tzinfo=_TZ),
        )
        midnight = datetime(2026, 7, 11, 0, tzinfo=_TZ)

        assert slot_windows_by_local_date([slot], _TZ) == {
            date(2026, 7, 10): [(slot.start_time, midnight)],
            date(2026, 7, 11): [(midnight, slot.end_time)],
        }
