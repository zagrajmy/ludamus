"""Template tags for the organizer panel's chrome."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django import template
from django.template.loader import render_to_string
from django.urls import reverse

if TYPE_CHECKING:
    from django.template import Context

register = template.Library()


@register.simple_tag(takes_context=True)
def sidebar_link(
    context: Context,
    *,
    url: str,
    icon: str,
    label: str,
    key: str = "",
    slug: str | None = None,
    new_tab: bool = False,
) -> str:
    """Render one entry in the panel sidebar.

    Reverses in Python rather than letting the template do `{% url … as … %}`,
    which swallows NoReverseMatch and renders `href=""` — a renamed route would
    silently point every sidebar entry at the current page. `reverse` raises.

    Resolving `active` here and handing the partial a closed context is how
    `{% tab %}` works (`tessera/tabs.py`): the caller says which page this *is*,
    never whether it is current, and the partial reads nothing ambient.

    Args:
        context: rendering context; read for `active_nav`.
        url: route name to reverse.
        icon: heroicon name.
        label: visible text, also the title attribute.
        key: the `active_nav` value that marks this entry current. Omit for a
            link that is never "where you are" — Print Materials opens a new
            tab and leaves the panel.
        slug: event slug, for the event-scoped routes that take one.
        new_tab: open in a new tab.

    Returns:
        HTML string of the sidebar anchor.
    """
    return render_to_string(
        "components/sidebar-link.html",
        {
            "href": reverse(url, kwargs={"slug": slug} if slug else {}),
            "icon": icon,
            "label": label,
            "active": bool(key) and key == context.get("active_nav"),
            "new_tab": new_tab,
        },
    )
