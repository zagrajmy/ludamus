"""Tests for panel helpers."""

from types import SimpleNamespace

from django.http import QueryDict

from ludamus.gates.web.django.panel import parse_requirement_selection


class TestParseRequirementSelection:
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
        ).scoped_to([SimpleNamespace(pk=1)])

        assert selection.requirements == {1: True}
        assert selection.order == [1]
