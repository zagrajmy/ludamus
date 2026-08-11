"""Tests for the panel chrome's sidebar_link tag."""

import pytest
from django.template import Context, Template, TemplateSyntaxError
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

    def test_a_key_no_page_sets_fails_loudly(self) -> None:
        # The counterpart of the route check: a key outside the closed set would
        # otherwise just never match active_nav, and nothing would highlight.
        tpl = Template(
            "{% load panel_tags %}"
            '{% sidebar_link url="multiverse:panel:guilds" icon="identification"'
            ' label="Guilds" key="guild" %}'
        )

        with pytest.raises(TemplateSyntaxError, match="guild"):
            tpl.render(Context())

    def test_escapes_the_label(self) -> None:
        tpl = Template(
            "{% load panel_tags %}"
            '{% sidebar_link url="multiverse:panel:guilds" icon="identification"'
            " label=evil %}"
        )

        html = tpl.render(Context({"evil": '"><script>alert(1)</script>'}))

        assert "<script>" not in html


CATEGORY = (
    "{% load panel_tags %}"
    '{% sidebar_cat key="sphere" label="Sphere" toggle_label="Toggle" %}'
    '{% sidebar_link url="multiverse:panel:guilds" icon="identification"'
    ' label="Guilds" key="guilds" %}'
    "{% endsidebar_cat %}"
)


class TestSidebarCat:
    def test_wraps_its_links_in_the_collapsible_body(self) -> None:
        html = Template(CATEGORY).render(Context())

        assert 'data-cat="sphere"' in html
        # The collapse rule hides .sidebar-cat-body, so a link outside it would
        # stay visible under a collapsed header.
        body = html.split('class="sidebar-cat-body')[1]
        assert 'href="/multiverse/panel/guilds/"' in body

    def test_points_the_header_at_the_region_it_collapses(self) -> None:
        html = Template(CATEGORY).render(Context())

        assert 'aria-controls="sidebar-cat-sphere"' in html
        assert 'id="sidebar-cat-sphere"' in html
        # panel-chrome.ts corrects this on load from the restored collapsed set.
        assert 'aria-expanded="true"' in html

    def test_links_inside_still_see_the_active_nav(self) -> None:
        html = Template(CATEGORY).render(Context({"active_nav": "guilds"}))

        assert 'aria-current="page"' in html
