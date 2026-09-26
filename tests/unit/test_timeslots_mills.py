from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from ludamus.mills.timeslots import MIDNIGHT, PROGRAMME_DAYS, event_opening_hours

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


class TestEventOpeningHours:
    _SNAP = 60

    def _hours(self, *, start, end, occupied=(), **extend):
        return event_opening_hours(
            start=start,
            end=end,
            occupied=occupied,
            tz=_TZ,
            snap_minutes=self._SNAP,
            **extend,
        )

    def test_the_event_clock_times_set_the_span(self):
        hours = self._hours(
            start=datetime(2026, 7, 10, 16, tzinfo=_TZ),
            end=datetime(2026, 7, 11, 22, tzinfo=_TZ),
        )

        assert hours.dates == [date(2026, 7, 10), date(2026, 7, 11)]
        assert hours.span == (16 * 60, 22 * 60)

    def test_the_span_snaps_out_to_the_slot_grid(self):
        hours = self._hours(
            start=datetime(2026, 7, 10, 16, 20, tzinfo=_TZ),
            end=datetime(2026, 7, 10, 21, 40, tzinfo=_TZ),
        )

        assert hours.span == (16 * 60, 22 * 60)

    def test_something_scheduled_early_widens_the_span(self):
        hours = self._hours(
            start=datetime(2026, 7, 10, 16, tzinfo=_TZ),
            end=datetime(2026, 7, 10, 22, tzinfo=_TZ),
            occupied=[
                (
                    datetime(2026, 7, 10, 8, 30, tzinfo=_TZ),
                    datetime(2026, 7, 10, 9, 30, tzinfo=_TZ),
                )
            ],
        )

        assert hours.span == (8 * 60, 22 * 60)

    def test_something_scheduled_off_the_event_dates_adds_its_day(self):
        hours = self._hours(
            start=datetime(2026, 7, 10, 16, tzinfo=_TZ),
            end=datetime(2026, 7, 10, 22, tzinfo=_TZ),
            occupied=[
                (
                    datetime(2026, 7, 12, 9, tzinfo=_TZ),
                    datetime(2026, 7, 12, 10, tzinfo=_TZ),
                )
            ],
        )

        assert hours.dates == [date(2026, 7, 10), date(2026, 7, 12)]
        assert hours.span == (9 * 60, 22 * 60)

    def test_the_extend_arguments_reach_hours_nothing_occupies(self):
        hours = self._hours(
            start=datetime(2026, 7, 10, 16, tzinfo=_TZ),
            end=datetime(2026, 7, 10, 22, tzinfo=_TZ),
            extend_before_hours=2,
            extend_after_hours=1,
        )

        assert hours.span == (14 * 60, 23 * 60)

    def test_extending_stops_at_the_edges_of_the_day(self):
        hours = self._hours(
            start=datetime(2026, 7, 10, 2, tzinfo=_TZ),
            end=datetime(2026, 7, 10, 23, tzinfo=_TZ),
            extend_before_hours=5,
            extend_after_hours=5,
        )

        assert hours.span == (0, 24 * 60)

    def test_an_event_starting_and_ending_on_the_same_clock_time_still_opens(self):
        hours = self._hours(
            start=datetime(2026, 7, 10, 10, tzinfo=_TZ),
            end=datetime(2026, 7, 12, 10, tzinfo=_TZ),
        )

        assert hours.dates == [date(2026, 7, 10), date(2026, 7, 11), date(2026, 7, 12)]
        assert hours.span == (10 * 60, 18 * 60)
