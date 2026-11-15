"""Unit tests for the availability contract: parts of a day or time slots."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from ludamus.pacts.availability import (
    AvailabilityDTO,
    DayPart,
    availability_value,
    group_by_day,
    in_reading_order,
    offered_parts_by_day,
    offered_times,
    offered_window,
    part_of,
    part_window,
    pick_offered,
    programme_date,
)
from ludamus.pacts.event import TimeSlotDTO

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


_SLOT = TimeSlotDTO(
    pk=7,
    start_time=datetime(2026, 10, 10, 10, tzinfo=_WARSAW),
    end_time=datetime(2026, 10, 10, 14, tzinfo=_WARSAW),
)
# Opens after midnight, so it belongs to Saturday's programme, not Sunday's.
_NIGHT_SLOT = TimeSlotDTO(
    pk=8,
    start_time=datetime(2026, 10, 11, 0, tzinfo=_WARSAW),
    end_time=datetime(2026, 10, 11, 5, tzinfo=_WARSAW),
)


class TestAvailabilityDTO:
    @pytest.mark.parametrize(
        "names", ({}, {"part": DayPart.EVENING, "time_slot": _SLOT})
    )
    def test_names_exactly_one_time(self, names: dict[str, object]) -> None:
        with pytest.raises(ValidationError, match="either a part of a day or a time"):
            AvailabilityDTO(day=_FRIDAY, **names)

    def test_offer_refuses_an_entry_built_past_validation(self) -> None:
        unchecked = AvailabilityDTO.model_construct(day=_FRIDAY)

        with pytest.raises(ValueError, match="either a part of a day or a time"):
            _ = unchecked.offer

    def test_offer_is_the_slot_or_the_part(self) -> None:
        assert AvailabilityDTO(day=_SATURDAY, time_slot=_SLOT).offer == _SLOT
        assert AvailabilityDTO(day=_SATURDAY, part=DayPart.NIGHT).offer == DayPart.NIGHT


class TestOfferedTimes:
    def test_offers_the_events_slots_in_the_order_they_open(self) -> None:
        offered = offered_times(
            start=_SLOT.start_time,
            end=_NIGHT_SLOT.end_time,
            slots=[_NIGHT_SLOT, _SLOT],
            tz=_WARSAW,
        )

        assert offered == [
            AvailabilityDTO(day=_SATURDAY, time_slot=_SLOT),
            AvailabilityDTO(day=_SATURDAY, time_slot=_NIGHT_SLOT),
        ]

    def test_offers_parts_of_the_day_where_the_event_lists_no_slots(self) -> None:
        offered = offered_times(
            start=datetime(2026, 10, 9, 16, tzinfo=_WARSAW),
            end=datetime(2026, 10, 9, 22, tzinfo=_WARSAW),
            slots=[],
            tz=_WARSAW,
        )

        assert offered == [
            AvailabilityDTO(day=_FRIDAY, part=DayPart.AFTERNOON),
            AvailabilityDTO(day=_FRIDAY, part=DayPart.EVENING),
        ]


class TestOfferedWindow:
    def test_a_slot_is_its_own_window(self) -> None:
        entry = AvailabilityDTO(day=_SATURDAY, time_slot=_SLOT)

        assert offered_window(entry, _WARSAW) == (_SLOT.start_time, _SLOT.end_time)

    def test_a_part_is_its_hours_on_that_day(self) -> None:
        entry = AvailabilityDTO(day=_FRIDAY, part=DayPart.EVENING)

        assert offered_window(entry, _WARSAW) == part_window(
            _FRIDAY, DayPart.EVENING, _WARSAW
        )


class TestInReadingOrder:
    def test_sorts_by_when_each_time_opens_not_by_name(self) -> None:
        night = AvailabilityDTO(day=_FRIDAY, part=DayPart.NIGHT)
        morning = AvailabilityDTO(day=_SATURDAY, part=DayPart.MORNING)
        afternoon = AvailabilityDTO(day=_FRIDAY, part=DayPart.AFTERNOON)

        assert in_reading_order([morning, night, afternoon], _WARSAW) == [
            afternoon,
            night,
            morning,
        ]


class TestAvailabilityValue:
    @pytest.mark.parametrize(
        ("entry", "expected"),
        (
            (AvailabilityDTO(day=_FRIDAY, part=DayPart.MORNING), "2026-10-09:morning"),
            (AvailabilityDTO(day=_FRIDAY, part=DayPart.NIGHT), "2026-10-09:night"),
            (AvailabilityDTO(day=_SATURDAY, time_slot=_SLOT), "slot:7"),
        ),
    )
    def test_spells_one_offered_time(
        self, entry: AvailabilityDTO, expected: str
    ) -> None:
        assert availability_value(entry) == expected


class TestPickOffered:
    _OFFERED = (
        AvailabilityDTO(day=_SATURDAY, time_slot=_SLOT),
        AvailabilityDTO(day=_SATURDAY, time_slot=_NIGHT_SLOT),
    )

    def test_round_trips_through_the_form(self) -> None:
        sent = [availability_value(entry) for entry in reversed(self._OFFERED)]

        assert pick_offered(sent, self._OFFERED) == list(self._OFFERED)

    @pytest.mark.parametrize(
        "raw", ("", "slot:9", "slot:", "slot:x", "2026-10-10:morning", "7", "morning")
    )
    def test_drops_what_is_not_on_offer(self, raw: str) -> None:
        assert pick_offered([raw], self._OFFERED) == []


class TestGroupByDay:
    def test_files_each_time_under_its_day_in_day_order(self) -> None:
        saturday = AvailabilityDTO(day=_SATURDAY, time_slot=_SLOT)
        friday_evening = AvailabilityDTO(day=_FRIDAY, part=DayPart.EVENING)
        friday_night = AvailabilityDTO(day=_FRIDAY, part=DayPart.NIGHT)

        assert group_by_day([saturday, friday_evening, friday_night]) == [
            (_FRIDAY, [friday_evening, friday_night]),
            (_SATURDAY, [saturday]),
        ]
