import pytest

from ludamus.gates.web.django.templatetags.cfp_tags import format_duration


class TestFormatDuration:
    def test_hours_and_minutes(self) -> None:
        assert format_duration("PT1H45M") == "1h 45min"

    def test_hours_only(self) -> None:
        assert format_duration("PT2H") == "2h"

    def test_minutes_only(self) -> None:
        assert format_duration("PT30M") == "30min"

    def test_empty_string(self) -> None:
        assert not format_duration("")

    def test_none_value(self) -> None:
        assert not format_duration(None)  # type: ignore[arg-type]

    def test_invalid_format(self) -> None:
        assert not format_duration("invalid")

    def test_pt_only(self) -> None:
        assert not format_duration("PT")

    @pytest.mark.parametrize("stored", ("P4H", "50min", "110m", "PT1H30MJUNK"))
    def test_unreadable_value_is_not_echoed(self, stored: str) -> None:
        assert not format_duration(stored)

    @pytest.mark.parametrize(
        ("iso", "expected"),
        (
            ("PT1H", "1h"),
            ("PT1H30M", "1h 30min"),
            ("PT12H", "12h"),
            ("PT5M", "5min"),
            ("PT59M", "59min"),
            ("PT3H15M", "3h 15min"),
        ),
    )
    def test_various_durations(self, iso: str, expected: str) -> None:
        assert format_duration(iso) == expected
