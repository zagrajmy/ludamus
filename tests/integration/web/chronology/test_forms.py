"""Unit tests for the accept-proposal form's availability helpers."""

from datetime import date

from ludamus.gates.web.django.chronology.forms import (
    availability_label,
    day_label,
    offered_times_hint,
)
from ludamus.pacts.availability import AvailabilityDTO, DayPart


class TestDayLabel:
    def test_names_the_weekday_beside_the_date(self) -> None:
        # The reviewer picks a day, so the weekday is the part they read;
        # "Mar 1" alone makes them count on a calendar.
        assert day_label(date(2026, 3, 1)) == "Sunday, Mar 1"


class TestAvailabilityLabel:
    def test_names_the_part_after_the_day(self) -> None:
        entry = AvailabilityDTO(day=date(2026, 3, 1), part=DayPart.EVENING)

        assert availability_label(entry) == "Sunday, Mar 1 evening"


class TestOfferedTimesHint:
    def test_lists_every_time_the_facilitator_offered(self) -> None:
        hint = offered_times_hint(
            [
                AvailabilityDTO(day=date(2026, 3, 1), part=DayPart.MORNING),
                AvailabilityDTO(day=date(2026, 3, 2), part=DayPart.NIGHT),
            ]
        )

        assert hint == (
            "The facilitator offered: Sunday, Mar 1 morning, Monday, Mar 2 night"
        )

    def test_says_nothing_when_no_time_was_offered(self) -> None:
        # An empty hint lets the field fall back to its own help text rather
        # than claiming the facilitator offered nothing at all.
        assert not offered_times_hint([])
