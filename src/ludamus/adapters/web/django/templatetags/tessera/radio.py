"""{% radio %} template tag — themed radio option with a slot label."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._registry import register
from ._utils import parse_tag_attrs
from .select import SelectNode

if TYPE_CHECKING:
    from django.template.base import Parser, Token


class RadioNode(SelectNode):
    """Renders a themed radio ``<input>`` labelled by its slot content."""

    _BOOLEAN_ATTRS = ("checked", "required", "disabled")
    _TEMPLATE = "components/radio.html"


@register.tag("radio")
def do_radio(parser: Parser, token: Token) -> RadioNode:
    """Parse ``{% radio ... %}...{% end_radio %}``.

    Returns:
        A RadioNode that renders a themed radio input labelled by its body.
    """
    attrs = parse_tag_attrs(parser, token)
    nodelist = parser.parse(("end_radio",))
    parser.delete_first_token()

    return RadioNode(nodelist, attrs)
