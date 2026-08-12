"""Template tags for the organizer panel's chrome."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django import template
from django.core.exceptions import ImproperlyConfigured
from django.template.loader import render_to_string
from django.urls import reverse

from ludamus.gates.web.django.panel import PANEL_CAT_KEYS, PANEL_NAV_KEYS

if TYPE_CHECKING:
    from django.template import Context
    from django.utils.safestring import SafeString

register = template.Library()


# One collapsible category of the panel sidebar, wrapping its links.
@register.simple_block_tag
def sidebar_cat(
    content: SafeString, *, key: str, label: str, extra_class: str = ""
) -> SafeString:
    if key not in PANEL_CAT_KEYS:
        msg = (
            f"sidebar_cat got key={key!r}, which is not a panel sidebar category;"
            f" expected one of {sorted(PANEL_CAT_KEYS)}"
        )
        raise template.TemplateSyntaxError(msg)

    return render_to_string(
        "panel/parts/sidebar-category.html",
        {"key": key, "label": label, "links": content, "extra_class": extra_class},
    )


# One entry in the panel sidebar. `key` is the `active_nav` value that marks this
# entry current; a link that is never "where you are" (Print Materials opens a
# new tab and leaves the panel) passes none. The route is reversed here rather
# than with `{% url … as … %}`, which swallows `NoReverseMatch` and leaves
# `href=""`.
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
) -> SafeString:
    if key is not None and key not in PANEL_NAV_KEYS:
        msg = (
            f"sidebar_link got key={key!r}, which is not a panel nav key;"
            f" expected one of {sorted(PANEL_NAV_KEYS)}"
        )
        raise template.TemplateSyntaxError(msg)

    # A different exception type because this is the view's mistake, not the
    # template's, and the message names the route because a TemplateResponse
    # renders after the view has returned, so the traceback no longer does.
    active_nav = context.get("active_nav")
    if active_nav is not None and active_nav not in PANEL_NAV_KEYS:
        match = getattr(context.get("request"), "resolver_match", None)
        blame = f"the view serving {match.view_name}" if match else "a panel view"
        msg = (
            f"{blame} put active_nav={active_nav!r} in the context, which is not"
            f" a panel nav key; expected one of {sorted(PANEL_NAV_KEYS)}"
        )
        raise ImproperlyConfigured(msg)

    return render_to_string(
        "panel/parts/sidebar-link.html",
        {
            "href": reverse(url, kwargs=url_kwargs),
            "icon": icon,
            "label": label,
            "active": key is not None and key == active_nav,
            "new_tab": new_tab,
        },
    )
