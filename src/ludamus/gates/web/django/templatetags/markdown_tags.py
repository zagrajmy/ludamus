from django import template
from django.utils.safestring import mark_safe

from ludamus.mills import render_markdown as _render_markdown

register = template.Library()


@register.filter
def render_markdown(text: str) -> str:
    if not text:
        return ""
    return mark_safe(_render_markdown(text))  # ruff:ignore[suspicious-mark-safe-usage]
