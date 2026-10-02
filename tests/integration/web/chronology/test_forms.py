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
    def test_drops_both_headings_when_no_preference_matches(self) -> None:
        # "Other times" alone would name a contrast with a group that is not
        # on the page. Preferences matching nothing read as no preference.
        choices = slot_choices([_slot(1, 10)], [99])

        assert choices == [("", "Choose a time…"), (1, "Sunday, Mar 1 · 11:00–13:00")]
