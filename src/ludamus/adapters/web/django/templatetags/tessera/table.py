"""{% tessera_table %} block tag — themed data table inside a card."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django import template
from django.utils.safestring import mark_safe

from ._registry import register
from ._utils import parse_tag_attrs

if TYPE_CHECKING:
    from django.template.base import FilterExpression, Parser, Token

_WRAPPER_CLASS = "card overflow-hidden"
_SCROLL_CLASS = "overflow-x-auto"
_TABLE_CLASS = "min-w-full divide-y divide-border"


class TableNode(template.Node):
    """Renders a themed table wrapped in a card with rounded-clipped corners."""

    def __init__(
        self, nodelist: template.NodeList, attrs: dict[str, FilterExpression]
    ) -> None:
        self.nodelist = nodelist
        self.attrs = attrs

    def render(self, context: template.Context) -> str:
        resolved: dict[str, object] = {
            k: v.resolve(context) for k, v in self.attrs.items()
        }
        extra_class = str(resolved.pop("class", "") or "")
        table_class = (
            f"{_TABLE_CLASS} {extra_class}".strip() if extra_class else _TABLE_CLASS
        )
        inner = self.nodelist.render(context)
        return mark_safe(  # noqa: S308
            f'<div class="{_WRAPPER_CLASS}">'
            f'<div class="{_SCROLL_CLASS}">'
            f'<table class="{table_class}">{inner}</table>'
            f"</div></div>"
        )


@register.tag("tessera_table")
def do_tessera_table(parser: Parser, token: Token) -> TableNode:
    """Parse ``{% tessera_table %}...{% end_tessera_table %}``.

    Returns:
        A TableNode that wraps its body in ``<div class="card overflow-hidden">
        <div class="overflow-x-auto"><table class="...">…</table></div></div>``.
        Caller writes their own ``<thead>``/``<tbody>``.
    """
    attrs = parse_tag_attrs(parser, token)
    nodelist = parser.parse(("end_tessera_table",))
    parser.delete_first_token()
    return TableNode(nodelist, attrs)
