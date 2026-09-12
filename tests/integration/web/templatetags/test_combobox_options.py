"""Combobox option payload contracts."""

import html as html_module
import json
import re

import pytest
from django.template import Context, Template


class TestComboboxOptionData:
    """The JSON the client reads instead of the option markup."""

    def _payload(self, slot: str, *, multiple: bool = False) -> dict[str, object]:
        tpl = Template(
            "{% load tessera %}"
            '{% tessera_combobox id="fruit" name="fruit" multiple=multiple %}'
            + slot
            + "{% endtessera_combobox %}"
        )
        html = tpl.render(Context({"multiple": multiple}))
        raw = re.search(
            r'<script id="fruit-options" type="application/json">(.*?)</script>',
            html,
            re.DOTALL,
        )
        assert raw is not None
        return json.loads(html_module.unescape(raw.group(1)))

    def test_carries_every_enabled_option_as_a_row(self) -> None:
        payload = self._payload(
            '<option value="a">Apple</option><option value="c">Cherry</option>'
        )
        assert payload["rows"] == [["a", "Apple"], ["c", "Cherry"]]

    def test_a_disabled_option_is_not_a_row(self) -> None:
        payload = self._payload(
            '<option value="" disabled selected>Any fruit</option>'
            '<option value="a">Apple</option>'
        )
        assert payload["rows"] == [["a", "Apple"]]

    def test_a_disabled_placeholder_keeps_its_label(self) -> None:
        payload = self._payload(
            '<option value="" disabled selected>Any fruit</option>'
            '<option value="a">Apple</option>'
        )
        assert payload["selected"] == [
            {"value": "", "label": "Any fruit", "disabled": True}
        ]

    def test_the_value_is_the_selected_option(self) -> None:
        payload = self._payload(
            '<option value="a">Apple</option><option value="c" selected>Cherry</option>'
        )
        assert payload["selected"] == [
            {"value": "c", "label": "Cherry", "disabled": False}
        ]

    def test_without_a_selection_the_first_option_stands(self) -> None:
        payload = self._payload(
            '<option value="a">Apple</option><option value="c">Cherry</option>'
        )
        assert payload["selected"] == [
            {"value": "a", "label": "Apple", "disabled": False}
        ]

    def test_multiple_preserves_all_selected_values(self) -> None:
        payload = self._payload(
            '<option value="a" selected>Apple</option>'
            '<option value="b">Banana</option>'
            '<option value="c" selected>Cherry</option>',
            multiple=True,
        )
        assert payload["selected"] == [
            {"value": "a", "label": "Apple", "disabled": False},
            {"value": "c", "label": "Cherry", "disabled": False},
        ]

    def test_multiple_does_not_select_the_first_option(self) -> None:
        payload = self._payload('<option value="a">Apple</option>', multiple=True)
        assert payload["selected"] == []

    def test_multiple_keeps_disabled_selection_metadata_outside_rows(self) -> None:
        payload = self._payload(
            '<option value="a" selected disabled>Apple</option>'
            '<option value="b" selected disabled>Banana</option>'
            '<option value="c" selected>Cherry</option>',
            multiple=True,
        )
        assert payload["selected"] == [
            {"value": "a", "label": "Apple", "disabled": True},
            {"value": "b", "label": "Banana", "disabled": True},
            {"value": "c", "label": "Cherry", "disabled": False},
        ]
        assert payload["rows"] == [["c", "Cherry"]]

    @pytest.mark.parametrize("multiple", (True, False))
    def test_empty_options_have_no_selection(self, *, multiple: bool) -> None:
        payload = self._payload("", multiple=multiple)
        assert payload["selected"] == []
        assert payload["rows"] == []
