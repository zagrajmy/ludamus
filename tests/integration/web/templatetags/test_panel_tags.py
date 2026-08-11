"""Tests for the panel chrome's sidebar_link tag."""

import pytest
from django.template import Context, Template
from django.urls import NoReverseMatch

GUILDS = (
    "{% load panel_tags %}"
    '{% sidebar_link url="multiverse:panel:guilds" icon="identification"'
    ' label="Guilds" key="guilds" %}'
)


class TestSidebarLink:
    def test_marks_the_entry_whose_key_is_the_active_nav(self) -> None:
        html = Template(GUILDS).render(Context({"active_nav": "guilds"}))

        assert 'href="/multiverse/panel/guilds/"' in html
        assert 'aria-current="page"' in html

    def test_leaves_other_entries_unmarked(self) -> None:
        html = Template(GUILDS).render(Context({"active_nav": "sphere-settings"}))

        assert 'href="/multiverse/panel/guilds/"' in html
        assert "aria-current" not in html

    def test_a_keyless_entry_is_never_current(self) -> None:
        # Print Materials leaves the panel, so no page it lands on is "here".
        tpl = Template(
            "{% load panel_tags %}"
            '{% sidebar_link url="web:chronology:event-print" slug="an-event"'
            ' icon="printer" label="Print" new_tab=True %}'
        )

        html = tpl.render(Context({"active_nav": ""}))

        assert 'target="_blank"' in html
        assert 'rel="noopener"' in html
        assert "aria-current" not in html

    def test_passes_leftover_kwargs_to_the_route(self) -> None:
        tpl = Template(
            "{% load panel_tags %}"
            '{% sidebar_link url="panel:cfp" slug="an-event" icon="rectangle-stack"'
            ' label="CfP" key="cfp" %}'
        )

        html = tpl.render(Context({"active_nav": "cfp"}))

        assert 'href="/panel/event/an-event/cfp/"' in html

    def test_a_renamed_route_fails_loudly(self) -> None:
        # The reason the tag reverses in Python: `{% url … as … %}` would
        # swallow this and render href="".
        tpl = Template(
            "{% load panel_tags %}"
            '{% sidebar_link url="panel:no-such-route" icon="home" label="Gone" %}'
        )

        with pytest.raises(NoReverseMatch):
            tpl.render(Context())

    def test_escapes_the_label(self) -> None:
        tpl = Template(
            "{% load panel_tags %}"
            '{% sidebar_link url="multiverse:panel:guilds" icon="identification"'
            " label=evil %}"
        )

        html = tpl.render(Context({"evil": '"><script>alert(1)</script>'}))

        assert "<script>" not in html
