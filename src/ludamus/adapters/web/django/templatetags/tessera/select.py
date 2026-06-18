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

    def __init__(
        self, nodelist: template.NodeList, attrs: dict[str, FilterExpression]
    ) -> None:
        self.nodelist = nodelist
        self.attrs = attrs

    def render(self, context: template.Context) -> str:
        """Render the select element via components/select.html.

        Any keyword passed to the tag is forwarded as an HTML attribute (e.g.
        ``id``, ``name``, ``onchange``); ``aria_*``/``data_*`` keywords become
        their hyphenated attribute (``aria-label``, ``data-foo``) since template
        kwargs cannot contain hyphens. ``class`` styles the element, and
        ``multiple``/``required``/``disabled`` render as bare boolean attributes.

        Returns:
            HTML string of the themed ``<select>`` element.
        """
        resolved: dict[str, object] = {
            k: v.resolve(context) for k, v in self.attrs.items()
        }

        extra_class = str(resolved.pop("class", ""))

        attr_parts: list[str] = []
        for key, value in resolved.items():
            if key in self._BOOLEAN_ATTRS:
                if value:
                    attr_parts.append(key)
                continue
            if not value:
                continue
            name = key.replace("_", "-") if key.startswith(("aria_", "data_")) else key
            attr_parts.append(f'{name}="{escape(str(value))}"')

        return render_to_string(
            "components/select.html",
            {
                "attrs": mark_safe(" ".join(attr_parts)),  # noqa: S308
                "extra_class": extra_class,
                "slot": mark_safe(self.nodelist.render(context)),  # noqa: S308
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
