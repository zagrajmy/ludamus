import pytest

from ludamus.pacts.durations import (
    MAX_DURATION_HOURS,
    InvalidDurationError,
    build_duration,
    format_duration,
    normalize_duration,
    parse_duration,
    parse_duration_part,
)


@pytest.mark.parametrize("stored", ("P4H", "PT1H30MJUNK", "JUNKPT1H"))
def test_parse_duration_reads_an_unreadable_value_as_zero(stored: str) -> None:
    assert parse_duration(stored) == (0, 0)


class TestParseDurationPart:
    @pytest.mark.parametrize("raw", ("24", "-1", "1.5", "01x"))
    def test_out_of_range_or_not_a_number(self, raw: str) -> None:
        with pytest.raises(InvalidDurationError):
            parse_duration_part(raw, maximum=MAX_DURATION_HOURS)

    def test_overlong_digit_string_is_rejected(self) -> None:
        with pytest.raises(InvalidDurationError):
            parse_duration_part("1" * 20, maximum=MAX_DURATION_HOURS)


class TestBuildDuration:
    @pytest.mark.parametrize(
        ("hours", "minutes", "expected"),
        ((0, 90, "PT1H30M"), (1, 60, "PT2H"), (0, 0, "")),
    )
    def test_minutes_carry_into_hours(
        self, hours: int, minutes: int, expected: str
    ) -> None:
        assert build_duration(hours=hours, minutes=minutes) == expected


class TestNormalizeDuration:
    # The values production actually held when issue #341 was filed.
    @pytest.mark.parametrize(
        ("stored", "expected"),
        (
            ("P4H", "PT4H"),
            ("50min", "PT50M"),
            ("110m", "PT1H50M"),
            ("110min", "PT1H50M"),
        ),
    )
    def test_production_values(self, stored: str, expected: str) -> None:
        assert normalize_duration(stored) == expected

    def test_canonical_value_round_trips(self) -> None:
        assert normalize_duration("PT1H30M") == "PT1H30M"

    # A guess is worse than a blank: a wrong length on screen reads exactly
    # like a right one, so text the pattern cannot consume whole is dropped.
    @pytest.mark.parametrize("ambiguous", ("1.5h", "2h30", "P1DT2H", "1h 2h"))
    def test_partially_readable_value_becomes_unset(self, ambiguous: str) -> None:
        assert not normalize_duration(ambiguous)

    def test_minutes_carry_into_hours(self) -> None:
        assert normalize_duration("1h 90m") == "PT2H30M"


@pytest.mark.parametrize("stored", ("PT", "P4H", "50min", "PT1H30MJUNK"))
def test_format_duration_does_not_echo_an_unreadable_value(stored: str) -> None:
    assert not format_duration(stored)
