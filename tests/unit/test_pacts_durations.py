import pytest

from ludamus.pacts.durations import build_duration, normalize_duration, parse_duration


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


class TestBuildDuration:
    @pytest.mark.parametrize(
        ("hours", "minutes", "expected"),
        ((1, 30, "PT1H30M"), (2, 0, "PT2H"), (0, 45, "PT45M"), (0, 0, "")),
    )
    def test_composition(self, hours: int, minutes: int, expected: str) -> None:
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

    @pytest.mark.parametrize("iso", ("PT4H", "PT1H30M", "PT50M"))
    def test_canonical_value_round_trips(self, iso: str) -> None:
        assert normalize_duration(iso) == iso

    @pytest.mark.parametrize("stored", ("", "invalid", "2026-06-05"))
    def test_unreadable_value_becomes_unset(self, stored: str) -> None:
        assert not normalize_duration(stored)

    def test_minutes_carry_into_hours(self) -> None:
        assert normalize_duration("1h 90m") == "PT2H30M"

    def test_idempotent(self) -> None:
        assert normalize_duration(normalize_duration("110min")) == "PT1H50M"
