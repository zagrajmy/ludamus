"""Session fact: one item of a session's facts line."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django import template
from django.template.loader import render_to_string

from ._registry import register
from ._utils import parse_tag_attrs

if TYPE_CHECKING:
    from django.template.base import FilterExpression, Parser, Token


class SessionFactNode(template.Node):
    _TEMPLATE = "components/_session_fact.html"

    def __init__(
        self, nodelist: template.NodeList, attrs: dict[str, FilterExpression]
    ) -> None:
        self.nodelist = nodelist
        self.attrs = attrs

    def render(self, context: template.Context) -> str:
        resolved = {key: attr.resolve(context) for key, attr in self.attrs.items()}
        return render_to_string(
            self._TEMPLATE,
            {
                "icon_name": resolved.get("icon", ""),
                "label": resolved.get("label", ""),
                "label_for": resolved.get("label_for", ""),
                "value": self.nodelist.render(context),
            },
        )


@register.tag("session_fact")
def do_session_fact(parser: Parser, token: Token) -> SessionFactNode:
    """Parse ``{% session_fact icon=... label=... %}...{% end_session_fact %}``.

    The body is the value: a fact the modal shows, or the field that writes it
    on the propose page, where ``label`` (and ``label_for``, the field's id)
    names it above the control.

    Returns:
        A SessionFactNode rendering ``components/_session_fact.html``.
    """
    attrs = parse_tag_attrs(parser, token)
    nodelist = parser.parse(("end_session_fact",))
    parser.delete_first_token()
    return SessionFactNode(nodelist, attrs)
