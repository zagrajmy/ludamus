"""Tests for the panel chrome's sidebar tags and the nav vocabulary they close."""

import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.template import Context, Template, TemplateSyntaxError
from django.template.loader import get_template
from django.urls import NoReverseMatch, resolve

from ludamus.gates.web.django.panel import PANEL_CAT_KEYS, PANEL_NAV_KEYS

if TYPE_CHECKING:
    from django.test import RequestFactory

GUILDS_URL = "/multiverse/panel/guilds/"
GUILDS = (
    "{% load panel_tags %}"
    '{% sidebar_link url="multiverse:panel:guilds" icon="identification"'
    ' label="Guilds" key="guilds" %}'
)


class TestSidebarLink:
    def test_marks_the_entry_whose_key_is_the_active_nav(self) -> None:
        html = Template(GUILDS).render(Context({"active_nav": "guilds"}))

        assert f'href="{GUILDS_URL}"' in html
        assert 'aria-current="page"' in html

    def test_leaves_other_entries_unmarked(self) -> None:
        html = Template(GUILDS).render(Context({"active_nav": "sphere-settings"}))

        assert f'href="{GUILDS_URL}"' in html
        assert 'aria-current="page"' not in html

    def test_a_keyless_entry_is_never_current(self) -> None:
        # Print Materials leaves the panel, so no page it lands on is "here".
        tpl = Template(
            "{% load panel_tags %}"
            '{% sidebar_link url="web:chronology:event-print" slug="an-event"'
            ' icon="printer" label="Print" new_tab=True %}'
        )

        html = tpl.render(Context())

        assert 'target="_blank"' in html
        assert 'rel="noopener"' in html
        assert 'aria-current="page"' not in html

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

    def test_an_active_nav_no_page_sets_names_the_view(
        self, rf: RequestFactory
    ) -> None:
        # The branch that fires in production: a TemplateResponse renders after
        # the view returns, so the message is the only thing left naming it.
        request = rf.get(GUILDS_URL)
        request.resolver_match = resolve(GUILDS_URL)

        with pytest.raises(ImproperlyConfigured, match="multiverse:panel:guilds"):
            Template(GUILDS).render(
                Context({"active_nav": "guildz", "request": request})
            )

    def test_an_active_nav_no_page_sets_still_raises_without_a_request(self) -> None:
        # Direct renders have no request to blame; the check still has to fire.
        with pytest.raises(ImproperlyConfigured, match="a panel view put"):
            Template(GUILDS).render(Context({"active_nav": "guildz"}))

    def test_escapes_the_label(self) -> None:
        tpl = Template(
            "{% load panel_tags %}"
            '{% sidebar_link url="multiverse:panel:guilds" icon="identification"'
            " label=evil %}"
        )

        html = tpl.render(Context({"evil": '"><script>alert(1)</script>'}))

        # Both halves matter: dropping the label entirely would satisfy the
        # negative assertion on its own.
        assert "&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt;" in html
        assert "<script>" not in html


CATEGORY = (
    "{% load panel_tags %}"
    '{% sidebar_cat key="sphere" label="Sphere" %}'
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
        assert f'href="{GUILDS_URL}"' in body

    def test_points_the_header_at_the_region_it_collapses(self) -> None:
        html = Template(CATEGORY).render(Context())

        assert 'aria-controls="sidebar-cat-sphere"' in html
        assert 'id="sidebar-cat-sphere"' in html
        # panel-chrome.ts corrects this on load from the restored collapsed set.
        assert 'aria-expanded="true"' in html

    def test_links_inside_still_see_the_active_nav(self) -> None:
        html = Template(CATEGORY).render(Context({"active_nav": "guilds"}))

        assert 'aria-current="page"' in html


class TestSidebarCatKey:
    def test_a_key_that_is_not_a_category_fails_loudly(self) -> None:
        # panel/base.html generates collapse rules from PANEL_CAT_KEYS, so a key
        # outside it renders a toggle that visibly does nothing — the same
        # dead-but-plausible failure sidebar_link guards.
        tpl = Template(
            "{% load panel_tags %}"
            '{% sidebar_cat key="reports" label="Reports" %}{% endsidebar_cat %}'
        )

        with pytest.raises(TemplateSyntaxError, match="reports"):
            tpl.render(Context())


def _sidebar_source() -> str:
    origin = get_template("panel/base.html").origin
    assert origin.name  # a filesystem-loaded template always has one

    return Path(origin.name).read_text(encoding="utf-8")


# The two Literals are only a single source of truth if `base.html` names every
# member. `{% sidebar_link %}` catches the other direction — a key or an
# active_nav outside the set — but a member nothing claims is invisible to it: a
# nav key no entry uses leaves its page silently unhighlighted, and a category
# with no collapse rules renders a toggle that does nothing. These read template
# source rather than rendered markup, which is source hygiene, not a UI
# assertion; the rendered side is Playwright's.
class TestSidebarCoverage:
    def test_every_nav_key_has_a_sidebar_entry(self) -> None:
        source = _sidebar_source()

        keys = set(re.findall(r'{% sidebar_link [^%]*key="([^"]+)"', source))

        assert keys == PANEL_NAV_KEYS

    def test_every_category_has_a_sidebar_entry(self) -> None:
        source = _sidebar_source()

        cats = set(re.findall(r'{% sidebar_cat key="([^"]+)"', source))

        assert cats == PANEL_CAT_KEYS

    # Both halves, because a category keeps its `html.catc-<key> ` prefix in one
    # rule when the other is missing — a hidden body under an unrotated chevron.
    def test_every_category_has_collapse_rules(self) -> None:
        source = _sidebar_source()

        missing = {
            f"{key}/{part}"
            for key in PANEL_CAT_KEYS
            for part in ("sidebar-cat-body", "sidebar-cat-chevron")
            if f'html.catc-{key} [data-cat="{key}"] .{part}' not in source
        }

        assert not missing
