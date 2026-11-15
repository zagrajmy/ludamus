"""The split view: a list, and beside it the one item it opened."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django import template
from django.template.loader import render_to_string

if TYPE_CHECKING:
    from django.utils.safestring import SafeString

register = template.Library()


# The whole page: with an item opened, the list and the item side by side on
# a wide screen; without one, the list alone.
@register.simple_block_tag(end_name="end_split_view")
def split_view(content: SafeString, *, opened: object) -> str:
    return render_to_string(
        "components/split_view.html", {"content": content, "opened": opened}
    )


# The list, which a narrow screen hides while an item is opened.
@register.simple_block_tag(end_name="end_split_view_list")
def split_view_list(content: SafeString, *, opened: object) -> str:
    return render_to_string(
        "components/split_view_list.html", {"content": content, "opened": opened}
    )


# One row of the list, marked while its item is the one opened: `item` names
# the row's, `opened` the opened one's, or nothing.
@register.simple_block_tag(end_name="end_split_view_row")
def split_view_row(
    content: SafeString,
    *,
    href: str,
    item: object,
    opened: object,
    extra_class: str = "",
) -> str:
    return render_to_string(
        "components/split_view_row.html",
        {
            "content": content,
            "href": href,
            "current": item == opened,
            "extra_class": extra_class,
        },
    )


# Back to the list, on a screen too narrow to show it beside the item.
@register.simple_tag
def split_view_back(*, href: str, label: str) -> str:
    return render_to_string(
        "components/split_view_back.html", {"href": href, "label": label}
    )
