"""Tests for tessera design-system component tags."""

import html as html_module
import json
import re
from unittest.mock import patch

import pytest
from django.template import Context, Template, TemplateSyntaxError
from heroicons import IconDoesNotExist


class TestIcon:
    def test_renders_outline_by_default(self) -> None:
        tpl = Template('{% load tessera %}{% icon "user" %}')
        html = tpl.render(Context())
        assert "<svg" in html
        assert "shrink-0" in html

    def test_renders_solid_variant(self) -> None:
        tpl = Template('{% load tessera %}{% icon "user" variant="solid" %}')
        html = tpl.render(Context())
        assert "<svg" in html

    def test_renders_mini_variant(self) -> None:
        tpl = Template('{% load tessera %}{% icon "user" variant="mini" %}')
        html = tpl.render(Context())
        assert "<svg" in html

    def test_passes_class_kwarg(self) -> None:
        tpl = Template('{% load tessera %}{% icon "user" class="w-5 h-5" %}')
        html = tpl.render(Context())
        assert "w-5 h-5" in html
        assert "shrink-0" in html

    def test_passes_style_kwarg(self) -> None:
        tpl = Template('{% load tessera %}{% icon "clock" style="color: var(--x)" %}')
        html = tpl.render(Context())
        assert "color: var(--x)" in html

    def test_escapes_xss_in_style_kwarg(self) -> None:
        tpl = Template('{% load tessera %}{% icon "clock" style=bad_style %}')
        html = tpl.render(Context({"bad_style": '" onload="alert(1)'}))
        assert 'onload="alert(1)"' not in html
        assert "&quot;" in html or "&amp;quot;" in html

    @patch("ludamus.adapters.web.django.templatetags.tessera.icon.settings")
    def test_missing_icon_raises_in_debug(self, mock_settings: object) -> None:
        mock_settings.DEBUG = True  # type: ignore[attr-defined]
        tpl = Template('{% load tessera %}{% icon "nonexistent-icon-xyz" %}')
        with pytest.raises(IconDoesNotExist):
            tpl.render(Context())

    @patch("ludamus.adapters.web.django.templatetags.tessera.icon.settings")
    def test_missing_icon_returns_empty_in_prod(self, mock_settings: object) -> None:
        mock_settings.DEBUG = False  # type: ignore[attr-defined]
        tpl = Template('{% load tessera %}{% icon "nonexistent-icon-xyz" %}')
        html = tpl.render(Context())
        assert not html.strip()


class TestCopyChip:
    @staticmethod
    def _render(text: str = "@ada") -> str:
        tpl = Template(
            "{% load tessera %}"
            "{% tessera_copy_chip handle label='Copy' copied_label='Copied!' %}"
        )
        return tpl.render(Context({"handle": text}))

    def test_renders_declarative_copy_markup(self) -> None:
        html = self._render()
        assert 'data-copy="@ada"' in html
        assert 'data-copied-label="Copied!"' in html
        assert "<svg" in html
        assert "onclick" not in html

    def test_labels_default_without_being_passed(self) -> None:
        tpl = Template("{% load tessera %}{% tessera_copy_chip '@ada' %}")
        html = tpl.render(Context())
        assert 'data-copied-label="Copied!"' in html
        assert 'title="Copy to clipboard"' in html

    def test_confirmation_is_a_live_region(self) -> None:
        html = self._render()
        assert "data-copy-popover" in html
        assert 'role="status"' in html
        assert 'aria-live="polite"' in html

    def test_copied_text_is_the_visible_clickable_label(self) -> None:
        html = self._render()
        assert "<button" in html
        assert ">@ada</code>" in html
        assert '<span class="sr-only">Copy</span>' in html

    def test_uses_icon_button_style(self) -> None:
        html = self._render()
        assert "icon-btn" in html
        assert 'title="Copy"' in html

    def test_popover_never_resizes_the_button(self) -> None:
        html = self._render()
        assert "absolute" in html
        assert "pointer-events-none" in html

    def test_escapes_xss_in_copy_text(self) -> None:
        html = self._render('"><script>alert(1)</script>')
        assert "<script>" not in html


class TestCopyPopover:
    def test_renders_live_region_hook(self) -> None:
        tpl = Template("{% load tessera %}{% tessera_copy_popover %}")
        html = tpl.render(Context())
        assert "data-copy-popover" in html
        assert 'role="status"' in html
        assert "pointer-events-none" in html


class TestCopyBlock:
    def test_button_variant_by_default(self) -> None:
        tpl = Template(
            "{% load tessera %}{% tessera_copy url %}Copy link{% endtessera_copy %}"
        )
        html = tpl.render(Context({"url": "https://x.test/e/1/"}))
        assert 'data-copy="https://x.test/e/1/"' in html
        assert 'data-copied-label="Copied!"' in html
        assert "btn btn-secondary" in html
        assert "Copy link" in html
        assert "data-copy-popover" in html
        assert "data-copy-origin" not in html

    def test_menu_item_variant_with_extra_layout_class(self) -> None:
        tpl = Template(
            "{% load tessera %}"
            '{% tessera_copy url variant="menu-item" class="rounded-t-lg" %}'
            "Copy link{% endtessera_copy %}"
        )
        html = tpl.render(Context({"url": "/e/1/"}))
        assert "hover:bg-bg-tertiary" in html
        assert "rounded-t-lg" in html
        assert "btn btn-secondary" not in html

    def test_origin_relative_paths_are_marked(self) -> None:
        tpl = Template(
            "{% load tessera %}"
            "{% tessera_copy path origin=True %}Copy{% endtessera_copy %}"
        )
        html = tpl.render(Context({"path": "/e/abc/"}))
        assert "data-copy-origin" in html

    def test_escapes_xss_in_payload(self) -> None:
        tpl = Template(
            "{% load tessera %}{% tessera_copy bad %}Copy{% endtessera_copy %}"
        )
        html = tpl.render(Context({"bad": '"><script>alert(1)</script>'}))
        assert "<script>alert" not in html

    def test_multiline_payload_survives_the_attribute(self) -> None:
        tpl = Template(
            "{% load tessera %}"
            "{% copy_lines 'Title' 'Room 5' as payload %}"
            "{% tessera_copy payload %}Copy details{% endtessera_copy %}"
        )
        html = tpl.render(Context())
        assert 'data-copy="Title\nRoom 5"' in html

    def test_copied_label_override(self) -> None:
        tpl = Template(
            "{% load tessera %}"
            "{% tessera_copy url copied_label='Got it' %}Copy{% endtessera_copy %}"
        )
        html = tpl.render(Context({"url": "/e/1/"}))
        assert 'data-copied-label="Got it"' in html

    def test_unknown_kwargs_raise_instead_of_vanishing(self) -> None:
        tpl = Template(
            "{% load tessera %}"
            "{% tessera_copy url copied_lable='typo' %}Copy{% endtessera_copy %}"
        )
        with pytest.raises(TemplateSyntaxError, match="copied_lable"):
            tpl.render(Context({"url": "/e/1/"}))

    def test_unknown_variant_raises(self) -> None:
        tpl = Template(
            "{% load tessera %}"
            '{% tessera_copy url variant="menu_item" %}Copy{% endtessera_copy %}'
        )
        with pytest.raises(TemplateSyntaxError, match="menu_item"):
            tpl.render(Context({"url": "/e/1/"}))


class TestCopyLines:
    def test_joins_parts_and_skips_empties(self) -> None:
        tpl = Template(
            "{% load tessera %}"
            "{% copy_lines 'Title' game 'Somewhere' as payload %}{{ payload }}"
        )
        html = tpl.render(Context({"game": ""}))
        assert "Title\nSomewhere" in html


class TestSelect:
    def test_renders_select_with_options(self) -> None:
        tpl = Template(
            "{% load tessera %}"
            '{% select id="color" name="color" %}'
            '<option value="r">Red</option>'
            "{% endselect %}"
        )
        html = tpl.render(Context())
        assert "<select" in html
        assert 'id="color"' in html
        assert 'name="color"' in html
        assert "<option" in html
        assert "Red" in html
        assert "</select>" in html

    def test_applies_ds_classes(self) -> None:
        tpl = Template('{% load tessera %}{% select name="x" %}{% endselect %}')
        html = tpl.render(Context())
        assert "rounded-lg" in html
        assert "border-border" in html
        assert "bg-bg-secondary" in html

    def test_required_attribute(self) -> None:
        tpl = Template(
            '{% load tessera %}{% select name="x" required=True %}{% endselect %}'
        )
        html = tpl.render(Context())
        assert "required" in html

    def test_multiple_attribute(self) -> None:
        tpl = Template(
            '{% load tessera %}{% select name="x" multiple=True %}{% endselect %}'
        )
        html = tpl.render(Context())
        assert "multiple" in html

    def test_forwards_arbitrary_attributes(self) -> None:
        tpl = Template(
            "{% load tessera %}"
            '{% select id="m" name="x" onchange="this.form.submit()" '
            'aria_label="Material" data_role="picker" %}{% endselect %}'
        )
        html = tpl.render(Context())
        assert 'onchange="this.form.submit()"' in html
        assert 'aria-label="Material"' in html
        assert 'data-role="picker"' in html

    def test_disabled_attribute(self) -> None:
        tpl = Template(
            '{% load tessera %}{% select name="x" disabled=True %}{% endselect %}'
        )
        html = tpl.render(Context())
        assert re.search(r"\sdisabled(?=[\s>])", html)

    def test_skips_falsy_attributes(self) -> None:
        tpl = Template(
            "{% load tessera %}"
            '{% select name="x" required=False data_role="" %}{% endselect %}'
        )
        html = tpl.render(Context())
        assert "required" not in html
        assert "data-role" not in html

    def test_extra_class(self) -> None:
        tpl = Template(
            '{% load tessera %}{% select name="x" class="mt-4" %}{% endselect %}'
        )
        html = tpl.render(Context())
        assert "mt-4" in html

    def test_options_from_context(self) -> None:
        tpl = Template(
            "{% load tessera %}"
            '{% select name="x" %}'
            "{% for opt in options %}"
            '<option value="{{ opt.0 }}">{{ opt.1 }}</option>'
            "{% endfor %}"
            "{% endselect %}"
        )
        html = tpl.render(Context({"options": [("a", "Alpha"), ("b", "Beta")]}))
        assert 'value="a"' in html
        assert "Alpha" in html
        assert 'value="b"' in html

    def test_escapes_xss_in_slot_content(self) -> None:
        tpl = Template(
            "{% load tessera %}"
            '{% select name="x" %}'
            '<option value="{{ val }}">{{ label }}</option>'
            "{% endselect %}"
        )
        html = tpl.render(
            Context({"val": '"><script>alert(1)</script>', "label": "<b>bad</b>"})
        )
        assert "<script>" not in html
        assert "&lt;script&gt;" in html or "&#x27;" in html


class TestComboboxOptionData:
    """The JSON the client reads instead of the option markup."""

    def _payload(self, slot: str) -> dict[str, object]:
        tpl = Template(
            "{% load tessera %}"
            '{% tessera_combobox id="fruit" name="fruit" %}'
            + slot
            + "{% endtessera_combobox %}"
        )
        html = tpl.render(Context())
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
        # Nobody may land on it, but it is what the field shows before anyone
        # picks — and it is not a row, so the label has to travel separately
        # or the control renders blank.
        payload = self._payload(
            '<option value="" disabled selected>Any fruit</option>'
            '<option value="a">Apple</option>'
        )
        assert payload["label"] == "Any fruit"
        assert not payload["value"]

    def test_the_value_is_the_selected_option(self) -> None:
        payload = self._payload(
            '<option value="a">Apple</option><option value="c" selected>Cherry</option>'
        )
        assert payload["value"] == "c"
        assert payload["label"] == "Cherry"

    def test_without_a_selection_the_first_option_stands(self) -> None:
        # What a single <select> does on its own: index 0 is current.
        payload = self._payload(
            '<option value="a">Apple</option><option value="c">Cherry</option>'
        )
        assert payload["value"] == "a"
        assert payload["label"] == "Apple"


class TestCombobox:
    def test_the_hidden_input_posts_under_the_given_name(self) -> None:
        # The upgraded control is what a form submits, and it takes its name
        # from this attribute. Empty here means the field silently never posts.
        tpl = Template(
            "{% load tessera %}"
            '{% tessera_combobox id="host" name="host" %}'
            '<option value="ada">Ada</option>'
            "{% endtessera_combobox %}"
        )
        html = tpl.render(Context())
        assert 'data-combobox-name="host"' in html
        # The scriptless <select> posts the same field, so it needs it too;
        # only ever one of the two exists.
        assert 'name="host"' in html

    def test_a_combobox_driving_no_form_needs_no_name(self) -> None:
        # The event page's host filter is one: it moves client-side state and
        # posts nothing, so a missing name is a valid shape, not a wiring bug.
        tpl = Template(
            "{% load tessera %}"
            '{% tessera_combobox id="host-filter" %}'
            '<option value="ada">Ada</option>'
            "{% endtessera_combobox %}"
        )
        assert 'data-combobox-name=""' in tpl.render(Context())

    def test_renders_select_and_shell(self) -> None:
        tpl = Template(
            "{% load tessera %}"
            '{% tessera_combobox id="host" name="host" %}'
            '<option value="ada">Ada</option>'
            "{% endtessera_combobox %}"
        )
        html = tpl.render(Context())
        assert "<select" in html
        assert 'id="host"' in html
        assert "Ada" in html
        assert "data-combobox" in html
        assert "data-combobox-shell" in html

    def test_input_carries_the_combobox_aria_contract(self) -> None:
        tpl = Template(
            '{% load tessera %}{% tessera_combobox id="host" name="host" %}'
            "{% endtessera_combobox %}"
        )
        html = tpl.render(Context())
        assert 'role="combobox"' in html
        assert 'aria-autocomplete="list"' in html
        assert 'aria-expanded="false"' in html
        assert 'id="host-input"' in html
        assert 'role="listbox"' in html
        assert 'id="host-listbox"' in html
        # The pattern asks for aria-controls only while the popup shows, so
        # the script adds it on open and takes it away on close.
        assert "aria-controls" not in html

    def test_option_row_template_carries_the_option_role(self) -> None:
        tpl = Template(
            '{% load tessera %}{% tessera_combobox id="host" name="host" %}'
            "{% endtessera_combobox %}"
        )
        html = tpl.render(Context())
        assert "<template" in html
        assert 'role="option"' in html

    def test_empty_state_is_visual_only(self) -> None:
        # The spoken copy goes to a live region combobox.ts keeps on the body:
        # one inside this popup would be display:none until it opened, and a
        # hidden live region announces nothing.
        tpl = Template(
            '{% load tessera %}{% tessera_combobox id="host" name="host" %}'
            "{% endtessera_combobox %}"
        )
        html = tpl.render(Context())
        assert "data-combobox-empty" in html
        assert 'aria-hidden="true"' in html
        assert "aria-live" not in html

    def test_toggle_is_out_of_the_tab_sequence(self) -> None:
        tpl = Template(
            '{% load tessera %}{% tessera_combobox id="host" name="host" %}'
            "{% endtessera_combobox %}"
        )
        html = tpl.render(Context())
        assert 'tabindex="-1"' in html

    def test_copy_is_overridable(self) -> None:
        tpl = Template(
            "{% load tessera %}"
            '{% tessera_combobox id="host" name="host" placeholder="Find a host" '
            'empty_text="No hosts" toggle_label="Open hosts" %}'
            "{% endtessera_combobox %}"
        )
        html = tpl.render(Context())
        assert 'placeholder="Find a host"' in html
        assert "No hosts" in html
        assert 'aria-label="Open hosts"' in html

    def test_class_lands_on_both_controls(self) -> None:
        tpl = Template(
            '{% load tessera %}{% tessera_combobox id="host" name="host" '
            'class="filter-input" %}{% endtessera_combobox %}'
        )
        html = tpl.render(Context())
        # The select and the input it is upgraded into.
        controls = 2
        assert html.count("filter-input") == controls

    def test_forwards_arbitrary_attributes_to_the_select(self) -> None:
        tpl = Template(
            '{% load tessera %}{% tessera_combobox id="host" name="host" '
            'required=True data_category="who" %}{% endtessera_combobox %}'
        )
        html = tpl.render(Context())
        assert "required" in html
        assert 'data-category="who"' in html


class TestTabs:
    def test_renders_tabs_nav(self) -> None:
        tpl = Template(
            "{% load tessera %}"
            '{% tabs %}{% tab "a" href="/a/" active=True %}A{% endtab %}{% endtabs %}'
        )
        html = tpl.render(Context())
        assert '<nav class="tab-nav flex items-end gap-1"' in html
        assert "</nav>" in html
        assert 'aria-selected="true"' in html
        assert 'data-tab="a"' in html
        assert 'href="/a/"' in html
        assert "A" in html

    def test_inactive_tab(self) -> None:
        tpl = Template(
            "{% load tessera %}"
            '{% tabs %}{% tab "b" href="/b/" %}B{% endtab %}{% endtabs %}'
        )
        html = tpl.render(Context())
        assert 'aria-selected="false"' in html
        assert 'class="tab-nav-link ' in html

    def test_active_tab_uses_shared_link_class(self) -> None:
        tpl = Template(
            "{% load tessera %}"
            '{% tabs %}{% tab "a" href="/a/" active=True %}A{% endtab %}{% endtabs %}'
        )
        html = tpl.render(Context())
        assert 'class="tab-nav-link ' in html
        assert "aria-selected:bg-bg-secondary" in html

    def test_active_tab_from_context(self) -> None:
        tpl = Template(
            "{% load tessera %}"
            '{% tabs %}{% tab "a" href="/a/" %}A{% endtab %}'
            '{% tab "b" href="/b/" %}B{% endtab %}'
            "{% endtabs %}"
        )
        html = tpl.render(Context({"active_tab": "b"}))
        assert 'aria-selected="false"' in html.split('href="/a/"')[1][:120]
        assert 'aria-selected="true"' in html.split('href="/b/"')[1][:120]

    def test_tab_with_icon(self) -> None:
        tpl = Template(
            "{% load tessera %}"
            '{% tabs %}{% tab "a" icon="user" href="/a/" %}A{% endtab %}{% endtabs %}'
        )
        html = tpl.render(Context())
        assert "<svg" in html

    def test_tabs_extra_class(self) -> None:
        tpl = Template(
            "{% load tessera %}"
            '{% tabs class="px-6 pt-4" %}'
            '{% tab "a" href="/" %}A{% endtab %}'
            "{% endtabs %}"
        )
        html = tpl.render(Context())
        assert "px-6 pt-4" in html

    def test_tab_href_from_context(self) -> None:
        tpl = Template(
            "{% load tessera %}"
            '{% tabs %}{% tab "a" href=my_url %}A{% endtab %}{% endtabs %}'
        )
        html = tpl.render(Context({"my_url": "/dynamic/"}))
        assert 'href="/dynamic/"' in html

    def test_tab_escapes_href(self) -> None:
        tpl = Template(
            "{% load tessera %}"
            '{% tabs %}{% tab "a" href=bad_url %}A{% endtab %}{% endtabs %}'
        )
        html = tpl.render(Context({"bad_url": '"><script>alert(1)</script>'}))
        assert "<script>" not in html

    def test_tab_missing_key_raises(self) -> None:
        with pytest.raises(TemplateSyntaxError, match="requires at least a key"):
            Template("{% load tessera %}{% tabs %}{% tab %}X{% endtab %}{% endtabs %}")


class TestTabShellBody:
    def test_renders_wrapper_with_content(self) -> None:
        tpl = Template(
            "{% load tessera %}"
            '{% tab_shell_body class="space-y-4" %}Hello{% endtab_shell_body %}'
        )
        html = tpl.render(Context())
        assert "bg-bg-secondary" in html
        assert "space-y-4" in html
        assert "Hello" in html

    def test_include_with_body_partial(self) -> None:
        tpl = Template(
            '{% include "components/tab-shell-body.html"'
            ' with body_partial="components/design/_tab_shell_body.html" %}'
        )
        html = tpl.render(Context())
        assert "bg-bg-secondary" in html
        assert "Tab shell body" in html

    def test_tab_shell_renders_one_valid_component_boundary(self) -> None:
        tpl = Template(
            "{% load tessera %}"
            '{% tab_shell "components/design/_tab_shell_tabs.html" %}'
            "{% tab_shell_body %}Hello{% endtab_shell_body %}"
            "{% endtab_shell %}"
        )
        html = tpl.render(Context())
        assert "overflow-hidden rounded-2xl border border-border" in html
        assert "Personal" in html
        assert "Hello" in html

    def test_tab_shell_requires_closing_tag(self) -> None:
        with pytest.raises(TemplateSyntaxError):
            Template(
                "{% load tessera %}"
                '{% tab_shell "components/design/_tab_shell_tabs.html" %}'
            )


ICON_TOGGLE_ICONS = 2
SWITCHER_SEGMENTS = 3


class TestIconButton:
    def _render(self, extra: str = "") -> str:
        tpl = Template(
            "{% load tessera %}"
            '{% tessera_icon_button icon="x-mark" label="Close filters" '
            + extra
            + " %}"
        )
        return tpl.render(Context())

    def test_renders_a_button_carrying_the_icon(self) -> None:
        html = self._render()
        assert html.startswith('<button type="button"')
        assert "<svg" in html

    def test_names_the_button_for_screen_readers(self) -> None:
        # The icon is decorative precisely because the label carries the name.
        html = self._render()
        assert 'aria-label="Close filters"' in html
        assert 'aria-hidden="true"' in html

    def test_refuses_to_render_without_a_label(self) -> None:
        # A button whose only content is an icon and which has no label is a
        # button no screen reader can announce, so it must not render at all.
        tpl = Template(
            '{% load tessera %}{% tessera_icon_button icon="x-mark" label="" %}'
        )
        with pytest.raises(ValueError, match="its icon is not a name"):
            tpl.render(Context())

    def test_forwards_extra_attrs_as_hyphenated(self) -> None:
        assert 'id="filter-close"' in self._render('id="filter-close"')
        assert 'data-close="1"' in self._render('data_close="1"')

    def test_is_not_styled_as_a_text_button(self) -> None:
        # Its own primitive, not a btn variant: a filled pill would compete
        # with the content it sits on top of.
        html = self._render()
        assert "btn" not in html
        assert "bg-transparent" in html

    def test_size_scales_padding_and_icon(self) -> None:
        assert "p-1.5" in self._render('size="sm"')
        assert "w-4 h-4" in self._render('size="sm"')
        assert "p-2" in self._render()

    def test_disabled_marks_the_button_disabled(self) -> None:
        assert " disabled" in self._render("disabled=True")


class TestIconToggle:
    def _render(self, extra: str = "") -> str:
        tpl = Template(
            "{% load tessera %}"
            '{% tessera_icon_toggle on_icon="speaker-wave" off_icon="speaker-x-mark" '
            'label="Toggle sound" ' + extra + " %}"
        )
        return tpl.render(Context())

    def test_renders_hidden_checkbox_in_label(self) -> None:
        html = self._render()
        assert html.startswith("<label")
        assert 'type="checkbox"' in html
        assert 'class="peer sr-only"' in html
        assert "rounded-full" in html

    def test_defaults_to_unchecked(self) -> None:
        assert " checked" not in self._render()

    def test_checked_sets_checked_attr(self) -> None:
        assert " checked" in self._render("checked=True")

    def test_renders_accessible_label(self) -> None:
        html = self._render()
        assert '<span class="sr-only">Toggle sound</span>' in html

    def test_swaps_icons_by_checked_state(self) -> None:
        html = self._render()
        assert "peer-checked:block" in html
        assert "peer-checked:hidden" in html
        assert html.count("<svg") == ICON_TOGGLE_ICONS

    def test_checked_state_is_not_primary(self) -> None:
        assert "primary" not in self._render("checked=True").replace(
            "outline-primary", ""
        )

    def test_renders_title(self) -> None:
        assert 'title="Interface sound"' in self._render('title="Interface sound"')

    def test_boolean_data_attr_is_bare(self) -> None:
        html = self._render("data_sound_toggle=True")
        assert "data-sound-toggle" in html
        assert 'data-sound-toggle="' not in html

    def test_valued_data_attr(self) -> None:
        assert 'data-role="switch"' in self._render('data_role="switch"')

    def test_skips_falsy_data_attr(self) -> None:
        html = self._render("data_role=False")
        assert "data-role" not in html

    def test_rejects_non_data_attr(self) -> None:
        with pytest.raises(ValueError, match="only accepts data_"):
            self._render('class="leak"')

    def test_escapes_data_attr_value(self) -> None:
        tpl = Template(
            "{% load tessera %}"
            '{% tessera_icon_toggle on_icon="speaker-wave" off_icon="speaker-x-mark" '
            "label=lbl data_role=bad %}"
        )
        html = tpl.render(Context({"lbl": "x", "bad": '"><script>alert(1)</script>'}))
        assert "<script>alert(1)" not in html


class TestSwitcher:
    def _render(self, *, selected: str = "light") -> str:
        tpl = Template(
            "{% load tessera %}"
            '{% tessera_switcher name="theme" selected="' + selected + '" %}'
            '{% tessera_segment "system" icon="computer-desktop" %}System'
            "{% endtessera_segment %}"
            '{% tessera_segment "light" icon="sun" %}Light{% endtessera_segment %}'
            '{% tessera_segment "dark" icon="moon" %}Dark{% endtessera_segment %}'
            "{% endtessera_switcher %}"
        )
        return tpl.render(Context())

    def test_renders_radiogroup(self) -> None:
        html = self._render()
        assert "<fieldset" in html
        assert 'role="radiogroup"' in html

    def test_renders_a_segment_per_value(self) -> None:
        html = self._render()
        assert 'value="system"' in html
        assert 'value="light"' in html
        assert 'value="dark"' in html
        assert html.count("<svg") == SWITCHER_SEGMENTS

    def test_segments_share_the_group_name(self) -> None:
        assert self._render().count('name="theme"') == SWITCHER_SEGMENTS

    def test_selected_segment_is_checked(self) -> None:
        html = self._render(selected="light")
        assert re.search(r'id="theme-light"[^>]*\schecked', html)
        assert not re.search(r'id="theme-system"[^>]*\schecked', html)

    def test_uses_peer_checked_styling(self) -> None:
        assert "peer-checked:bg-bg-secondary" in self._render()

    def test_renders_segment_labels(self) -> None:
        html = self._render()
        assert "System" in html
        assert "Light" in html
        assert "Dark" in html

    def test_segment_missing_value_raises(self) -> None:
        with pytest.raises(TemplateSyntaxError, match="requires at least a value"):
            Template(
                "{% load tessera %}{% tessera_switcher %}"
                "{% tessera_segment %}X{% endtessera_segment %}"
                "{% endtessera_switcher %}"
            )

    def test_requires_name(self) -> None:
        with pytest.raises(TemplateSyntaxError, match="requires a name"):
            Template(
                "{% load tessera %}{% tessera_switcher %}"
                '{% tessera_segment "a" %}A{% endtessera_segment %}'
                "{% endtessera_switcher %}"
            ).render(Context())

    def test_segment_outside_switcher_raises(self) -> None:
        with pytest.raises(TemplateSyntaxError, match="must be used inside"):
            Template(
                '{% load tessera %}{% tessera_segment "a" %}A{% endtessera_segment %}'
            ).render(Context())
