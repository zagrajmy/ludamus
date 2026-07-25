"""Unit tests for panel helpers."""

import pytest

from ludamus.gates.web.django.chronology.panel.views.columns import (
    FACILITATOR_COLUMNS,
    BuiltinColumn,
    builtin_columns,
)
from ludamus.gates.web.django.chronology.panel.views.venues import suggest_copy_name
from ludamus.pacts import FacilitatorListItemDTO


class TestSuggestCopyName:
    """Tests for suggest_copy_name helper function."""

    def test_adds_copy_suffix_to_plain_name(self) -> None:
        assert suggest_copy_name("Main Hall") == "Main Hall (Copy)"

    def test_increments_copy_suffix(self) -> None:
        assert suggest_copy_name("Main Hall (Copy)") == "Main Hall (Copy 2)"

    def test_increments_numbered_copy_suffix(self) -> None:
        assert suggest_copy_name("Main Hall (Copy 2)") == "Main Hall (Copy 3)"

    def test_increments_high_numbered_copy_suffix(self) -> None:
        assert suggest_copy_name("Main Hall (Copy 99)") == "Main Hall (Copy 100)"

    @pytest.mark.parametrize(
        ("name", "expected"),
        (
            ("Room (A)", "Room (A) (Copy)"),
            ("Room (Copy) Extra", "Room (Copy) Extra (Copy)"),
            ("(Copy)", "(Copy) (Copy)"),
        ),
    )
    def test_handles_names_with_parentheses_that_are_not_copy_suffix(
        self, name: str, expected: str
    ) -> None:
        assert suggest_copy_name(name) == expected


class TestFacilitatorBuiltinCell:
    """Tests for the facilitator list's built-in column cells."""

    @staticmethod
    def _facilitator() -> FacilitatorListItemDTO:
        return FacilitatorListItemDTO(
            accreditation_type="none",
            display_name="Alice",
            pk=1,
            session_count=3,
            slug="alice",
            user_id=None,
        )

    @pytest.mark.parametrize(
        ("key", "expected"), (("name", "Alice"), ("sessions", "3"))
    )
    def test_renders_cell_for_key(self, key: str, expected: str) -> None:
        cell = FACILITATOR_COLUMNS[key].cell
        assert cell is not None
        assert cell(self._facilitator()) == expected


class TestBuiltins:
    """Tests for the guard tying the render table to the mill's key list."""

    def test_rejects_a_key_the_mill_never_offers(self) -> None:
        with pytest.raises(ValueError, match="built-in columns don't match"):
            builtin_columns(("name",), {"mystery": BuiltinColumn(label="Mystery")})
