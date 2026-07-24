"""{% select %} template tag — themed select element."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django import template
from django.template.loader import render_to_string
from django.utils.html import escape
from django.utils.safestring import mark_safe

from ._registry import register
from ._utils import parse_tag_attrs

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

        # `class` styles the element; every other keyword is forwarded as an
        # HTML attribute on the <select>.
        extra_class = str(resolved.pop("class", ""))

        attr_parts: list[str] = []
        for key, value in resolved.items():
            if key in self._BOOLEAN_ATTRS:
                if value:
                    attr_parts.append(key)
                continue
            # `value=0` is a legitimate radio value — only drop absent attrs.
            if value is None or (isinstance(value, str) and not value):
                continue
            # Template kwargs can't contain hyphens, so aria_*/data_* keywords
            # map onto their hyphenated attributes (aria_label -> aria-label).
            name = key.replace("_", "-") if key.startswith(("aria_", "data_")) else key
            attr_parts.append(f'{name}="{escape(str(value))}"')

        return render_to_string(
            self._TEMPLATE,
            {
                "attrs": mark_safe(  # ruff: ignore[suspicious-mark-safe-usage]
                    " ".join(attr_parts)
                ),
                "extra_class": extra_class,
                "slot": mark_safe(  # ruff: ignore[suspicious-mark-safe-usage]
                    self.nodelist.render(context)
                ),
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
