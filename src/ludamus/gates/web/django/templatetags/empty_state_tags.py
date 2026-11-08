"""The empty state: what a list or page says when it has nothing to show."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django import template
from django.template.loader import render_to_string

if TYPE_CHECKING:
    from django.utils.safestring import SafeString

register = template.Library()


# The block holds the actions (a button, a link), if any.
@register.simple_block_tag(end_name="end_empty_state")
def empty_state(content: SafeString, *, icon: str, title: str, text: str = "") -> str:
    return render_to_string(
        "components/empty_state.html",
        {"icon": icon, "title": title, "text": text, "actions": content.strip()},
    )
