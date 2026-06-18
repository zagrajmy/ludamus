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
