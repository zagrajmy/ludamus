"""Tags for the session body that the modal and the propose page share."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django import template
from django.template.base import token_kwargs
from django.template.loader import render_to_string

if TYPE_CHECKING:
    from django.template.base import FilterExpression, Parser, Token

register = template.Library()


class SessionFactNode(template.Node):
    def __init__(
        self, nodelist: template.NodeList, kwargs: dict[str, FilterExpression]
    ) -> None:
        self.nodelist = nodelist
        self.kwargs = kwargs

    def render(self, context: template.Context) -> str:
        resolved = {key: value.resolve(context) for key, value in self.kwargs.items()}
        return render_to_string(
            "components/_session_fact.html",
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

    One item of a session's facts line. The body is the value: a fact the
    modal shows, or the field that writes it on the propose page, where
    ``label`` (and ``label_for``, the field's id) names it above the control.

    Returns:
        A SessionFactNode rendering ``components/_session_fact.html``.
    """
    kwargs = token_kwargs(token.split_contents()[1:], parser)
    nodelist = parser.parse(("end_session_fact",))
    parser.delete_first_token()
    return SessionFactNode(nodelist, kwargs)
