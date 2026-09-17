"""Unit tests for the accept-proposal form's day helpers."""

from datetime import date

from ludamus.gates.web.django.chronology.forms import day_label, offered_days_hint


class TestDayLabel:
    def test_names_the_weekday_beside_the_date(self) -> None:
        # The reviewer picks a day, so the weekday is the part they read;
        # "Mar 1" alone makes them count on a calendar.
        assert day_label(date(2026, 3, 1)) == "Sunday, Mar 1"


class TestOfferedDaysHint:
    def test_lists_every_day_the_facilitator_offered(self) -> None:
        hint = offered_days_hint([date(2026, 3, 1), date(2026, 3, 2)])

        assert hint == "The facilitator offered: Sunday, Mar 1, Monday, Mar 2"

    def test_says_nothing_when_no_day_was_offered(self) -> None:
        # An empty hint lets the field fall back to its own help text rather
        # than claiming the facilitator offered nothing at all.
        assert not offered_days_hint([])
