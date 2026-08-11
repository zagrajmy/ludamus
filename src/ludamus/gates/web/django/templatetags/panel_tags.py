"""Template tags for the organizer panel's chrome."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django import template
from django.template.loader import render_to_string
from django.urls import reverse

from ludamus.gates.web.django.panel import PANEL_NAV_KEYS

if TYPE_CHECKING:
    from django.template import Context
    from django.utils.safestring import SafeString

register = template.Library()


# One collapsible category of the panel sidebar, wrapping its links. Extracted
# for the same reason as `{% sidebar_link %}`: the header markup was four
# byte-identical copies of a 148-character class attribute.
@register.simple_block_tag
def sidebar_cat(content: SafeString, *, key: str, label: str, toggle_label: str) -> str:
    return render_to_string(
        "components/sidebar-category.html",
        {"key": key, "label": label, "toggle_label": toggle_label, "links": content},
    )


# One entry in the panel sidebar. `key` is the `active_nav` value that marks
# this entry current; a link that is never "where you are" (Print Materials
# opens a new tab and leaves the panel) passes none.
# Nothing here fails by rendering something plausible-but-dead. `{% url … as … %}`
# would swallow a renamed route and leave `href=""`, so the route is reversed
# here, where `reverse` raises. A misspelling on either side of the highlight
# comparison would just never match, so both sides are checked against the
# closed set — this tag is where the ~50 views that set `active_nav` and the 14
# call sites that name a `key` finally meet, and the only place that can.
# Resolving `active` here also hands the partial a closed context, the same
# split as `{% tab %}` in tessera/tabs.py.
@register.simple_tag(takes_context=True)
def sidebar_link(
    context: Context,
    *,
    url: str,
    icon: str,
    label: str,
    key: str | None = None,
    new_tab: bool = False,
    **url_kwargs: str,
) -> str:
    active_nav = context.get("active_nav")
    for name, value in (("key", key), ("active_nav", active_nav)):
        if value not in {None, "", *PANEL_NAV_KEYS}:
            msg = f"sidebar_link got {name}={value!r}, which is not a panel nav key"
            raise template.TemplateSyntaxError(msg)

    return render_to_string(
        "components/sidebar-link.html",
        {
            "href": reverse(url, kwargs=url_kwargs),
            "icon": icon,
            "label": label,
            "active": key is not None and key == active_nav,
            "new_tab": new_tab,
        },
    )
