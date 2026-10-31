import string
import sys

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ludamus.pacts.durations import (
    MAX_DURATION_HOURS,
    MAX_DURATION_MINUTES,
    InvalidDurationError,
    build_duration,
    format_duration,
    normalize_duration,
    parse_duration,
    parse_duration_part,
)

_ISDIGIT_TRUE = tuple(
    char for code in range(sys.maxunicode + 1) if (char := chr(code)).isdigit()
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

    # `str.isdigit` is true for all of these; `int` also reads the Arabic-Indic.
    @pytest.mark.parametrize("raw", ("²", "1²", "³", "\u0661", "\u0661\u0662"))
    def test_a_digit_outside_ascii_is_refused(self, raw: str) -> None:
        with pytest.raises(InvalidDurationError):
            parse_duration_part(raw, maximum=MAX_DURATION_HOURS)

    @pytest.mark.parametrize(
        ("raw", "maximum", "expected"),
        (
            (" 23 ", MAX_DURATION_HOURS, MAX_DURATION_HOURS),
            ("07", MAX_DURATION_MINUTES, 7),
            ("", MAX_DURATION_MINUTES, 0),
        ),
    )
    def test_ascii_digits_are_read(self, raw: str, maximum: int, expected: int) -> None:
        assert parse_duration_part(raw, maximum=maximum) == expected

    @given(
        raw=st.text(
            alphabet=st.sampled_from(_ISDIGIT_TRUE)
            | st.sampled_from(string.digits + " "),
            max_size=3,
        ),
        maximum=st.sampled_from((MAX_DURATION_HOURS, MAX_DURATION_MINUTES)),
    )
    def test_a_part_is_ascii_digits_in_range_or_refused(
        self, raw: str, maximum: int
    ) -> None:
        try:
            part = parse_duration_part(raw, maximum=maximum)
        except InvalidDurationError:
            return
        assert raw.strip().isascii()
        assert 0 <= part <= maximum


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
