"""Bottom sheet: a card from ``lg`` up, a modal sheet below it."""

from typing import TYPE_CHECKING

from django import template
from django.template.loader import render_to_string

from ._registry import register
from ._utils import parse_tag_attrs

if TYPE_CHECKING:
    from django.template.base import FilterExpression, Parser, Token

_REQUIRED = ("id", "title", "close_url")


class BottomSheetNode(template.Node):
    def __init__(
        self, nodelist: template.NodeList, attrs: dict[str, FilterExpression]
    ) -> None:
        self.nodelist = nodelist
        self.attrs = attrs

    def render(self, context: template.Context) -> str:
        resolved = {k: v.resolve(context) for k, v in self.attrs.items()}
        return render_to_string(
            "components/bottom-sheet.html",
            {
                "id": resolved["id"],
                "title": resolved["title"],
                "close_url": resolved["close_url"],
                "height": resolved.get("height") or "half",
                "open": bool(resolved.get("open")),
                "level": resolved.get("level") or 2,
                "content": self.nodelist.render(context),
            },
        )


@register.tag
def bottom_sheet(parser: Parser, token: Token) -> BottomSheetNode:
    attrs = parse_tag_attrs(parser, token)
    if missing := [key for key in _REQUIRED if key not in attrs]:
        msg = f"'bottom_sheet' tag requires {', '.join(missing)}"
        raise template.TemplateSyntaxError(msg)
    nodelist = parser.parse(("end_bottom_sheet",))
    parser.delete_first_token()
    return BottomSheetNode(nodelist, attrs)
