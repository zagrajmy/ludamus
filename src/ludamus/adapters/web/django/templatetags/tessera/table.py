"""{% tessera_table %} block tag — themed data table inside a card.

A hoverable body row whose default navigation is Edit or Details should mark
that link with ``data-row-action``. Clicks on the row background then follow
it; Delete and other controls stay their own targets. The overlay lives in
``index.css``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django import template
from django.utils.html import format_html

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
        return format_html(
            '<div class="{}"><div class="{}"><table class="{}">{}</table></div></div>',
            _WRAPPER_CLASS,
            _SCROLL_CLASS,
            table_class,
            self.nodelist.render(context),
        )


@register.tag("tessera_table")
def do_tessera_table(parser: Parser, token: Token) -> TableNode:
    """Parse ``{% tessera_table %}...{% endtessera_table %}``.

    Returns:
        A TableNode that wraps its body in ``<div class="card overflow-hidden">
        <div class="overflow-x-auto"><table class="...">…</table></div></div>``.
        Caller writes their own ``<thead>``/``<tbody>``. Mark the default
        action (Edit / Details) on a hoverable row with ``data-row-action``.
    """
    attrs = parse_tag_attrs(parser, token)
    nodelist = parser.parse(("endtessera_table",))
    parser.delete_first_token()
    return TableNode(nodelist, attrs)
