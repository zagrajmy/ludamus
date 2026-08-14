import pytest

from ludamus.pacts.durations import (
    MAX_DURATION_HOURS,
    MAX_DURATION_MINUTES,
    InvalidDurationError,
    build_duration,
    duration_choices,
    duration_from_parts,
    format_duration,
    normalize_duration,
    parse_duration,
    parse_duration_part,
    stepper_parts,
)


class TestParseDuration:
    @pytest.mark.parametrize(
        ("iso", "expected"),
        (("PT1H30M", (1, 30)), ("PT2H", (2, 0)), ("PT45M", (0, 45))),
    )
    def test_canonical_value(self, iso: str, expected: tuple[int, int]) -> None:
        assert parse_duration(iso) == expected

    @pytest.mark.parametrize(
        "stored", ("", "PT", "P4H", "50min", "PT1H30MJUNK", "JUNKPT1H")
    )
    def test_unreadable_value(self, stored: str) -> None:
        assert parse_duration(stored) == (0, 0)


class TestParseDurationPart:
    def test_blank_is_unset(self) -> None:
        assert parse_duration_part("", maximum=MAX_DURATION_HOURS) == 0
        assert parse_duration_part("  ", maximum=MAX_DURATION_MINUTES) == 0

    def test_plain_number(self) -> None:
        hours = MAX_DURATION_HOURS // 2
        assert parse_duration_part(str(hours), maximum=MAX_DURATION_HOURS) == hours

    @pytest.mark.parametrize("raw", ("24", "60", "-1", "1.5", "1e2", "abc", "01x"))
    def test_out_of_range_or_not_a_number(self, raw: str) -> None:
        with pytest.raises(InvalidDurationError):
            parse_duration_part(raw, maximum=MAX_DURATION_HOURS)

    def test_overlong_digit_string_is_rejected(self) -> None:
        with pytest.raises(InvalidDurationError):
            parse_duration_part("1" * 20, maximum=MAX_DURATION_HOURS)


class TestStepperParts:
    @pytest.mark.parametrize(
        ("iso", "expected"),
        (
            ("PT1H30M", ("1", "30")),
            ("PT2H", ("2", "")),
            ("PT45M", ("", "45")),
            ("", ("", "")),
            ("P4H", ("", "")),
        ),
    )
    def test_blank_when_zero(self, iso: str, expected: tuple[str, str]) -> None:
        assert stepper_parts(iso) == expected


class TestDurationFromParts:
    def test_composition(self) -> None:
        assert duration_from_parts(hours="1", minutes="30") == "PT1H30M"

    def test_blank_is_unset(self) -> None:
        assert not duration_from_parts(hours="", minutes="")

    def test_invalid_part_is_rejected(self) -> None:
        with pytest.raises(InvalidDurationError):
            duration_from_parts(hours="24", minutes="0")


class TestBuildDuration:
    @pytest.mark.parametrize(
        ("hours", "minutes", "expected"),
        ((1, 30, "PT1H30M"), (2, 0, "PT2H"), (0, 45, "PT45M"), (0, 0, "")),
    )
    def test_composition(self, hours: int, minutes: int, expected: str) -> None:
        assert build_duration(hours=hours, minutes=minutes) == expected

    @pytest.mark.parametrize(
        ("hours", "minutes", "expected"),
        ((0, 90, "PT1H30M"), (1, 60, "PT2H"), (0, 120, "PT2H")),
    )
    def test_minutes_carry_into_hours(
        self, hours: int, minutes: int, expected: str
    ) -> None:
        assert build_duration(hours=hours, minutes=minutes) == expected

    def test_composed_value_is_readable_back(self) -> None:
        assert parse_duration(build_duration(hours=0, minutes=90)) == (1, 30)


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

    @pytest.mark.parametrize("iso", ("PT4H", "PT1H30M", "PT50M"))
    def test_canonical_value_round_trips(self, iso: str) -> None:
        assert normalize_duration(iso) == iso

    @pytest.mark.parametrize("stored", ("", "invalid", "2026-06-05"))
    def test_unreadable_value_becomes_unset(self, stored: str) -> None:
        assert not normalize_duration(stored)

    # A guess is worse than a blank: a wrong length on screen reads exactly
    # like a right one, so text the pattern cannot consume whole is dropped.
    @pytest.mark.parametrize(
        "ambiguous", ("1.5h", "2h30", "P1DT2H", "5 maja", "-5m", "1h 2h")
    )
    def test_partially_readable_value_becomes_unset(self, ambiguous: str) -> None:
        assert not normalize_duration(ambiguous)

    def test_minutes_carry_into_hours(self) -> None:
        assert normalize_duration("1h 90m") == "PT2H30M"

    def test_idempotent(self) -> None:
        assert normalize_duration(normalize_duration("110min")) == "PT1H50M"


class TestFormatDuration:
    @pytest.mark.parametrize(
        ("iso", "expected"),
        (
            ("PT1H45M", "1h 45min"),
            ("PT1H", "1h"),
            ("PT12H", "12h"),
            ("PT30M", "30min"),
            ("PT5M", "5min"),
            ("PT3H15M", "3h 15min"),
        ),
    )
    def test_canonical_value(self, iso: str, expected: str) -> None:
        assert format_duration(iso) == expected

    def test_none_value(self) -> None:
        assert not format_duration(None)

    @pytest.mark.parametrize(
        "stored", ("", "PT", "invalid", "P4H", "50min", "110m", "PT1H30MJUNK")
    )
    def test_unreadable_value_is_not_echoed(self, stored: str) -> None:
        assert not format_duration(stored)


class TestDurationChoices:
    def test_labelled_options_only(self) -> None:
        assert duration_choices(["PT1H", "P4H", "PT30M"]) == [
            ("PT1H", "1h"),
            ("PT30M", "30min"),
        ]

    def test_no_readable_option(self) -> None:
        assert not duration_choices(["P4H", ""])
