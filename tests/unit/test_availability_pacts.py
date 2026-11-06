"""Unit tests for the part-of-day availability contract."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from ludamus.pacts.availability import (
    AvailabilityDTO,
    DayPart,
    availability_from_value,
    availability_value,
    offered_parts_by_day,
    part_of,
    part_window,
    programme_date,
)

_WARSAW = ZoneInfo("Europe/Warsaw")

# A Friday-to-Sunday convention, in the days the wizard would offer.
_FRIDAY = date(2026, 10, 9)
_SATURDAY = date(2026, 10, 10)
_SUNDAY = date(2026, 10, 11)

# Three parts on Friday, four on Saturday, two on Sunday.
_OFFERED_PAIRS_OVER_A_WEEKEND = 9


class TestProgrammeDate:
    def test_the_small_hours_belong_to_the_day_before(self) -> None:
        # Nobody at a convention calls 02:00 on Saturday "Saturday"; it is
        # still Friday night to them, and to the facilitator who offered it.
        moment = datetime(2026, 10, 10, 2, 0, tzinfo=UTC)

        assert programme_date(moment, UTC) == _FRIDAY

    def test_the_day_turns_over_at_six(self) -> None:
        assert programme_date(datetime(2026, 10, 10, 5, 59, tzinfo=UTC), UTC) == _FRIDAY
        assert (
            programme_date(datetime(2026, 10, 10, 6, 0, tzinfo=UTC), UTC) == _SATURDAY
        )

    def test_daytime_is_its_own_date(self) -> None:
        moment = datetime(2026, 10, 10, 14, 30, tzinfo=UTC)

        assert programme_date(moment, UTC) == _SATURDAY

    def test_the_answer_is_read_in_the_events_own_timezone(self) -> None:
        # 04:30 UTC is 06:30 in Warsaw, past the turnover there and short of
        # it here, so the two zones disagree about which day it is.
        moment = datetime(2026, 10, 10, 4, 30, tzinfo=UTC)

        assert programme_date(moment, _WARSAW) == _SATURDAY
        assert programme_date(moment, UTC) == _FRIDAY


class TestPartOf:
    @pytest.mark.parametrize(
        ("hour", "expected"),
        (
            (6, DayPart.MORNING),
            (11, DayPart.MORNING),
            (12, DayPart.AFTERNOON),
            (17, DayPart.AFTERNOON),
            (18, DayPart.EVENING),
            (23, DayPart.EVENING),
        ),
    )
    def test_names_the_part_the_hour_falls_in(
        self, hour: int, expected: DayPart
    ) -> None:
        moment = datetime(2026, 10, 10, hour, 0, tzinfo=UTC)

        assert part_of(moment, UTC) == expected

    @pytest.mark.parametrize("hour", (0, 1, 3, 5))
    def test_midnight_to_six_is_the_night_of_the_day_before(self, hour: int) -> None:
        moment = datetime(2026, 10, 10, hour, 0, tzinfo=UTC)

        assert part_of(moment, UTC) == DayPart.NIGHT
        assert programme_date(moment, UTC) == _FRIDAY

    def test_the_part_is_read_in_the_events_own_timezone(self) -> None:
        # 23:00 UTC is already 01:00 in Warsaw, which is the night, not the
        # evening the UTC clock still shows.
        moment = datetime(2026, 10, 10, 23, 0, tzinfo=UTC)

        assert part_of(moment, _WARSAW) == DayPart.NIGHT
        assert part_of(moment, UTC) == DayPart.EVENING


class TestPartWindow:
    @pytest.mark.parametrize(
        ("part", "expected"),
        (
            (
                DayPart.MORNING,
                (
                    datetime(2026, 10, 10, 6, 0, tzinfo=UTC),
                    datetime(2026, 10, 10, 12, 0, tzinfo=UTC),
                ),
            ),
            (
                DayPart.AFTERNOON,
                (
                    datetime(2026, 10, 10, 12, 0, tzinfo=UTC),
                    datetime(2026, 10, 10, 18, 0, tzinfo=UTC),
                ),
            ),
            (
                DayPart.EVENING,
                (
                    datetime(2026, 10, 10, 18, 0, tzinfo=UTC),
                    datetime(2026, 10, 11, 0, 0, tzinfo=UTC),
                ),
            ),
        ),
    )
    def test_resolves_a_part_to_real_instants(
        self, part: DayPart, expected: tuple[datetime, datetime]
    ) -> None:
        assert part_window(_SATURDAY, part, UTC) == expected

    def test_the_night_spills_into_the_next_date(self) -> None:
        # Night is 24-30 rather than 0-6 precisely so that it lands after the
        # evening it follows instead of before the morning it precedes.
        assert part_window(_SATURDAY, DayPart.NIGHT, UTC) == (
            datetime(2026, 10, 11, 0, 0, tzinfo=UTC),
            datetime(2026, 10, 11, 6, 0, tzinfo=UTC),
        )

    def test_every_window_holds_the_instants_it_claims(self) -> None:
        for part in DayPart:
            start, _ = part_window(_SATURDAY, part, UTC)

            assert part_of(start, UTC) == part
            assert programme_date(start, UTC) == _SATURDAY


class TestOfferedPartsByDay:
    def test_offers_only_the_parts_the_events_hours_reach(self) -> None:
        # A Friday-16:00 opening has no morning to offer, and an 18:00 close
        # on Sunday has no evening: asking about either would be asking the
        # facilitator to offer a time the event does not have.
        offered = offered_parts_by_day(
            start=datetime(2026, 10, 9, 16, 0, tzinfo=UTC),
            end=datetime(2026, 10, 11, 18, 0, tzinfo=UTC),
            tz=UTC,
        )

        assert offered == [
            (_FRIDAY, [DayPart.AFTERNOON, DayPart.EVENING, DayPart.NIGHT]),
            (
                _SATURDAY,
                [DayPart.MORNING, DayPart.AFTERNOON, DayPart.EVENING, DayPart.NIGHT],
            ),
            (_SUNDAY, [DayPart.MORNING, DayPart.AFTERNOON]),
        ]

    def test_leaves_out_a_day_with_nothing_to_offer(self) -> None:
        # The event closes at 05:00 Saturday, which is still Friday night, so
        # Saturday never gets a row of its own.
        offered = offered_parts_by_day(
            start=datetime(2026, 10, 9, 20, 0, tzinfo=UTC),
            end=datetime(2026, 10, 10, 5, 0, tzinfo=UTC),
            tz=UTC,
        )

        assert offered == [(_FRIDAY, [DayPart.EVENING, DayPart.NIGHT])]

    def test_an_inverted_range_offers_nothing(self) -> None:
        assert not offered_parts_by_day(
            start=datetime(2026, 10, 11, 18, 0, tzinfo=UTC),
            end=datetime(2026, 10, 9, 16, 0, tzinfo=UTC),
            tz=UTC,
        )

    def test_an_empty_range_offers_nothing(self) -> None:
        moment = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)

        assert not offered_parts_by_day(start=moment, end=moment, tz=UTC)

    def test_every_offered_pair_can_be_answered_with(self) -> None:
        offered = offered_parts_by_day(
            start=datetime(2026, 10, 9, 16, 0, tzinfo=UTC),
            end=datetime(2026, 10, 11, 18, 0, tzinfo=UTC),
            tz=UTC,
        )

        answers = [
            AvailabilityDTO(day=day, part=part)
            for day, parts in offered
            for part in parts
        ]

        assert len(answers) == _OFFERED_PAIRS_OVER_A_WEEKEND
        assert answers[0] == AvailabilityDTO(day=_FRIDAY, part=DayPart.AFTERNOON)


class TestAvailabilityValue:
    @pytest.mark.parametrize(
        ("part", "expected"),
        ((DayPart.MORNING, "2026-10-09:morning"), (DayPart.NIGHT, "2026-10-09:night")),
    )
    def test_joins_the_day_and_the_part(self, part: DayPart, expected: str) -> None:
        assert availability_value(_FRIDAY, part) == expected

    def test_round_trips_through_the_form(self) -> None:
        offered = AvailabilityDTO(day=_SATURDAY, part=DayPart.EVENING)

        assert (
            availability_from_value(availability_value(offered.day, offered.part))
            == offered
        )


class TestAvailabilityFromValue:
    def test_reads_a_pair_a_form_sent(self) -> None:
        assert availability_from_value("2026-10-11:afternoon") == AvailabilityDTO(
            day=_SUNDAY, part=DayPart.AFTERNOON
        )

    @pytest.mark.parametrize(
        "raw",
        (
            "",
            "2026-10-09",
            "2026-10-09:teatime",
            "not-a-date:morning",
            "2026-13-40:morning",
            ":morning",
            "morning",
        ),
    )
    def test_refuses_text_that_does_not_spell_a_pair(self, raw: str) -> None:
        assert availability_from_value(raw) is None
