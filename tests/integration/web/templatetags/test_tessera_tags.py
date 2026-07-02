"""Tests for tessera design-system component tags."""

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


class TestSelect:
    def test_renders_select_with_options(self) -> None:
        tpl = Template(
            "{% load tessera %}"
            '{% select id="color" name="color" %}'
            '<option value="r">Red</option>'
            "{% end_select %}"
        )
        html = tpl.render(Context())
        assert "<select" in html
        assert 'id="color"' in html
        assert 'name="color"' in html
        assert "<option" in html
        assert "Red" in html
        assert "</select>" in html

    def test_applies_ds_classes(self) -> None:
        tpl = Template('{% load tessera %}{% select name="x" %}{% end_select %}')
        html = tpl.render(Context())
        assert "rounded-lg" in html
        assert "border-border" in html
        assert "bg-bg-secondary" in html

    def test_required_attribute(self) -> None:
        tpl = Template(
            '{% load tessera %}{% select name="x" required=True %}{% end_select %}'
        )
        html = tpl.render(Context())
        assert "required" in html

    def test_multiple_attribute(self) -> None:
        tpl = Template(
            '{% load tessera %}{% select name="x" multiple=True %}{% end_select %}'
        )
        html = tpl.render(Context())
        assert "multiple" in html

    def test_forwards_arbitrary_attributes(self) -> None:
        tpl = Template(
            "{% load tessera %}"
            '{% select id="m" name="x" onchange="this.form.submit()" '
            'aria_label="Material" data_role="picker" %}{% end_select %}'
        )
        html = tpl.render(Context())
        assert 'onchange="this.form.submit()"' in html
        assert 'aria-label="Material"' in html
        assert 'data-role="picker"' in html

    def test_disabled_attribute(self) -> None:
        tpl = Template(
            '{% load tessera %}{% select name="x" disabled=True %}{% end_select %}'
        )
        html = tpl.render(Context())
        # Match the bare boolean attribute, not the base classes' `disabled:*`.
        assert re.search(r"\sdisabled(?=[\s>])", html)

    def test_skips_falsy_attributes(self) -> None:
        tpl = Template(
            "{% load tessera %}"
            '{% select name="x" required=False data_role="" %}{% end_select %}'
        )
        html = tpl.render(Context())
        assert "required" not in html
        assert "data-role" not in html

    def test_extra_class(self) -> None:
        tpl = Template(
            '{% load tessera %}{% select name="x" class="mt-4" %}{% end_select %}'
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
            "{% end_select %}"
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
            "{% end_select %}"
        )
        html = tpl.render(
            Context({"val": '"><script>alert(1)</script>', "label": "<b>bad</b>"})
        )
        assert "<script>" not in html
        assert "&lt;script&gt;" in html or "&#x27;" in html


class TestTabs:
    def test_renders_tabs_nav(self) -> None:
        tpl = Template(
            "{% load tessera %}"
            '{% tabs %}{% tab "a" href="/a/" active=True %}A{% end_tab %}{% end_tabs %}'
        )
        html = tpl.render(Context())
        assert "<nav" in html
        assert "</nav>" in html
        assert 'aria-selected="true"' in html
        assert 'href="/a/"' in html
        assert "A" in html

    def test_inactive_tab(self) -> None:
        tpl = Template(
            "{% load tessera %}"
            '{% tabs %}{% tab "b" href="/b/" %}B{% end_tab %}{% end_tabs %}'
        )
        html = tpl.render(Context())
        assert 'aria-selected="false"' in html

    def test_active_tab_classes(self) -> None:
        tpl = Template(
            "{% load tessera %}"
            '{% tabs %}{% tab "a" href="/a/" active=True %}A{% end_tab %}{% end_tabs %}'
        )
        html = tpl.render(Context())
        assert 'aria-selected="true"' in html

    def test_tab_with_icon(self) -> None:
        tpl = Template(
            "{% load tessera %}"
            '{% tabs %}{% tab "a" icon="user" href="/a/" %}A{% end_tab %}{% end_tabs %}'
        )
        html = tpl.render(Context())
        assert "<svg" in html

    def test_tabs_extra_class(self) -> None:
        tpl = Template(
            "{% load tessera %}"
            '{% tabs class="px-6 pt-4" %}'
            '{% tab "a" href="/" %}A{% end_tab %}'
            "{% end_tabs %}"
        )
        html = tpl.render(Context())
        assert "px-6 pt-4" in html

    def test_tab_href_from_context(self) -> None:
        tpl = Template(
            "{% load tessera %}"
            '{% tabs %}{% tab "a" href=my_url %}A{% end_tab %}{% end_tabs %}'
        )
        html = tpl.render(Context({"my_url": "/dynamic/"}))
        assert 'href="/dynamic/"' in html

    def test_tab_escapes_href(self) -> None:
        tpl = Template(
            "{% load tessera %}"
            '{% tabs %}{% tab "a" href=bad_url %}A{% end_tab %}{% end_tabs %}'
        )
        html = tpl.render(Context({"bad_url": '"><script>alert(1)</script>'}))
        assert "<script>" not in html

    def test_tab_missing_key_raises(self) -> None:
        with pytest.raises(TemplateSyntaxError, match="requires at least a key"):
            Template(
                "{% load tessera %}{% tabs %}{% tab %}X{% end_tab %}{% end_tabs %}"
            )


ICON_TOGGLE_ICONS = 2
SWITCHER_SEGMENTS = 3


class TestIconToggle:
    def _render(self, extra: str = "") -> str:
        tpl = Template(
            "{% load tessera %}"
            '{% tessera_icon_toggle on_icon="speaker-wave" off_icon="speaker-x-mark" '
            'label="Toggle sound" ' + extra + " %}"
        )
        return tpl.render(Context())

    def test_renders_toggle_button(self) -> None:
        html = self._render()
        assert 'type="button"' in html
        assert "rounded-full" in html

    def test_defaults_to_unpressed(self) -> None:
        assert 'aria-pressed="false"' in self._render()

    def test_pressed_sets_aria_pressed(self) -> None:
        assert 'aria-pressed="true"' in self._render("pressed=True")

    def test_renders_accessible_label(self) -> None:
        html = self._render()
        assert '<span class="sr-only">Toggle sound</span>' in html

    def test_swaps_icons_by_aria_pressed(self) -> None:
        html = self._render()
        assert "group-aria-pressed:block" in html
        assert "group-aria-pressed:hidden" in html
        assert html.count("<svg") == ICON_TOGGLE_ICONS

    def test_renders_title(self) -> None:
        assert 'title="Sound (Velvet)"' in self._render('title="Sound (Velvet)"')

    def test_boolean_data_attr_is_bare(self) -> None:
        html = self._render("data_velvet_toggle=True")
        assert "data-velvet-toggle" in html
        assert 'data-velvet-toggle="' not in html

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
            "{% end_tessera_segment %}"
            '{% tessera_segment "light" icon="sun" %}Light{% end_tessera_segment %}'
            '{% tessera_segment "dark" icon="moon" %}Dark{% end_tessera_segment %}'
            "{% end_tessera_switcher %}"
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
                "{% tessera_segment %}X{% end_tessera_segment %}"
                "{% end_tessera_switcher %}"
            )

    def test_requires_name(self) -> None:
        with pytest.raises(TemplateSyntaxError, match="requires a name"):
            Template(
                "{% load tessera %}{% tessera_switcher %}"
                '{% tessera_segment "a" %}A{% end_tessera_segment %}'
                "{% end_tessera_switcher %}"
            ).render(Context())

    def test_segment_outside_switcher_raises(self) -> None:
        with pytest.raises(TemplateSyntaxError, match="must be used inside"):
            Template(
                '{% load tessera %}{% tessera_segment "a" %}A{% end_tessera_segment %}'
            ).render(Context())
