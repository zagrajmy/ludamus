from django import template
from django.utils.safestring import SafeString

from ludamus.mills import render_markdown as _render_markdown

register = template.Library()


@register.filter
def render_markdown(text: str) -> str:
    if not text:
        return ""
    # `_render_markdown` runs the output through nh3 with an allow-list, so the
    # HTML is already sanitised. `format_html` would escape it back into
    # visible tags.
    return SafeString(_render_markdown(text))
