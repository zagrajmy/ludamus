"""Template tags for the organizer panel's chrome."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django import template
from django.template.loader import render_to_string
from django.urls import reverse

if TYPE_CHECKING:
    from django.template import Context

register = template.Library()


# One entry in the panel sidebar. `key` is the `active_nav` value that marks
# this entry current; a link that is never "where you are" (Print Materials
# opens a new tab and leaves the panel) passes none. Leftover kwargs are the
# route's URL kwargs.
# Reversing here rather than in the template is the point: `{% url … as … %}`
# swallows NoReverseMatch and renders `href=""`, so a renamed route would
# silently aim every sidebar entry at the current page. `reverse` raises.
# Resolving `active` here too hands the partial a closed context, the same
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
    return render_to_string(
        "components/sidebar-link.html",
        {
            "href": reverse(url, kwargs=url_kwargs),
            "icon": icon,
            "label": label,
            "active": key is not None and key == context.get("active_nav"),
            "new_tab": new_tab,
        },
    )
