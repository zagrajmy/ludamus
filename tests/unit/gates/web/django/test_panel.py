"""Unit tests for panel helpers."""

import pytest
from django.http import QueryDict

from ludamus.gates.web.django.chronology.panel.views.venues import suggest_copy_name
from ludamus.gates.web.django.panel import parse_requirement_selection


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


class TestParseRequirementSelection:
    def test_reads_requirements_and_order(self) -> None:
        post = QueryDict("field_1=required&field_2=optional&field_order=2,1")

        selection = parse_requirement_selection(
            post, prefix="field_", order_key="field_order"
        )

        assert selection.requirements == {1: True, 2: False}
        assert selection.order == [2, 1]

    def test_ignores_non_numeric_keys_and_order_entries(self) -> None:
        post = QueryDict("field_abc=required&field_1=required&field_order=abc,1,")

        selection = parse_requirement_selection(
            post, prefix="field_", order_key="field_order"
        )

        assert selection.requirements == {1: True}
        assert selection.order == [1]

    def test_scoped_to_drops_pks_outside_the_event(self) -> None:
        post = QueryDict("field_1=required&field_999=required&field_order=999,1")

        selection = parse_requirement_selection(
            post, prefix="field_", order_key="field_order"
        ).scoped_to({1})

        assert selection.requirements == {1: True}
        assert selection.order == [1]
