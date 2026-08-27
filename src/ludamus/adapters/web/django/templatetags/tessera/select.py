"""{% select %} template tag — themed select element."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django import template
from django.template.loader import render_to_string

from ._registry import register
from ._utils import format_tag_attrs, parse_tag_attrs

if TYPE_CHECKING:
    from django.template.base import FilterExpression, Parser, Token


class SelectNode(template.Node):
    """Renders a themed ``<select>`` wrapping slot content."""

    # Attributes rendered bare (no ``="value"``) when truthy.
    _BOOLEAN_ATTRS = ("multiple", "required", "disabled")
    _TEMPLATE = "components/select.html"

    def __init__(
        self, nodelist: template.NodeList, attrs: dict[str, FilterExpression]
    ) -> None:
        self.nodelist = nodelist
        self.attrs = attrs

    def render(self, context: template.Context) -> str:
        resolved: dict[str, object] = {
            k: v.resolve(context) for k, v in self.attrs.items()
        }

        # `class` styles the element and `has_errors` drives the error cues;
        # every other keyword is forwarded as an HTML attribute on the <select>.
        extra_class = str(resolved.pop("class", ""))
        has_errors = bool(resolved.pop("has_errors", False))

        return render_to_string(
            self._TEMPLATE,
            {
                "attrs": format_tag_attrs(resolved, boolean_attrs=self._BOOLEAN_ATTRS),
                "extra_class": extra_class,
                "has_errors": has_errors,
                "slot": self.nodelist.render(context),
            },
        )


@register.tag("select")
def do_select(parser: Parser, token: Token) -> SelectNode:
    """Parse ``{% select ... %}...{% end_select %}``.

    Returns:
        A SelectNode that renders a themed ``<select>`` wrapping its body.
    """
    attrs = parse_tag_attrs(parser, token)
    nodelist = parser.parse(("end_select",))
    parser.delete_first_token()

    return SelectNode(nodelist, attrs)
