"""Unit tests for the accept-proposal form's choice building."""

from datetime import UTC, datetime

from ludamus.gates.web.django.chronology.forms import slot_choices, slot_label
from ludamus.pacts import TimeSlotDTO


def _slot(pk: int, hour: int) -> TimeSlotDTO:
    return TimeSlotDTO(
        pk=pk,
        start_time=datetime(2026, 3, 1, hour, 0, tzinfo=UTC),
        end_time=datetime(2026, 3, 1, hour + 2, 0, tzinfo=UTC),
    )


class TestSlotLabel:
    def test_reads_the_slot_in_the_event_time_zone(self) -> None:
        # The template filter this replaced localised first (it is registered
        # `expects_localtime`), so a label built in Python has to as well or
        # every time on the page shifts by the configured offset.
        assert slot_label(_slot(1, 10)) == "Sunday, Mar 1 · 11:00–13:00"


class TestSlotChoices:
    def test_lists_slots_flat_behind_a_blank_when_none_are_preferred(self) -> None:
        choices = slot_choices([_slot(1, 10), _slot(2, 14)], [])

        assert choices == [
            ("", "Choose a time…"),
            (1, "Sunday, Mar 1 · 11:00–13:00"),
            (2, "Sunday, Mar 1 · 15:00–17:00"),
        ]

    def test_floats_the_preferred_slots_into_their_own_group(self) -> None:
        choices = slot_choices([_slot(1, 10), _slot(2, 14)], [2])

        assert choices == [
            ("", "Choose a time…"),
            ("Preferred by the facilitator", [(2, "Sunday, Mar 1 · 15:00–17:00")]),
            ("Other times", [(1, "Sunday, Mar 1 · 11:00–13:00")]),
        ]

    def test_omits_the_other_group_when_every_slot_is_preferred(self) -> None:
        choices = slot_choices([_slot(1, 10)], [1])

        assert choices == [
            ("", "Choose a time…"),
            ("Preferred by the facilitator", [(1, "Sunday, Mar 1 · 11:00–13:00")]),
        ]
