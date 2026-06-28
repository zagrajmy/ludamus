import re
from re import Match

from django import template
from django.utils.safestring import mark_safe

from ludamus.mills import render_markdown as _render_markdown

register = template.Library()

_HEADING_RE = re.compile(r"<(/?)h([1-6])(\s[^>]*)?>")


def _shift_headings(html: str) -> str:
    def _sub(m: Match[str]) -> str:
        slash, level, attrs = m.group(1), int(m.group(2)), m.group(3) or ""
        return f"<{slash}h{min(level + 2, 6)}{'' if slash else attrs}>"
    return _HEADING_RE.sub(_sub, html)


@register.filter
def render_markdown(text: str) -> str:
    if not text:
        return ""
    return mark_safe(_shift_headings(_render_markdown(text)))
