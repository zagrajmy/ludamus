"""Tab shell layout wrappers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django import template
from django.template.loader import render_to_string

from ._registry import register
from ._utils import parse_tag_attrs

if TYPE_CHECKING:
    from django.template.base import FilterExpression, Parser, Token

_TAB_SHELL_TOKEN_LENGTH = 2


class TabShellBodyNode(template.Node):
    def __init__(
        self, nodelist: template.NodeList, attrs: dict[str, FilterExpression]
    ) -> None:
        self.nodelist = nodelist
        self.attrs = attrs

    def render(self, context: template.Context) -> str:
        resolved: dict[str, str] = {
            k: v.resolve(context) for k, v in self.attrs.items()
        }
        return render_to_string(
            "components/tab-shell-body.html",
            {
                "extra_class": resolved.pop("class", ""),
                "body_partial": "",
                "content": self.nodelist.render(context),
            },
        )


@register.tag
def tab_shell_body(parser: Parser, token: Token) -> TabShellBodyNode:
    attrs = parse_tag_attrs(parser, token)
    nodelist = parser.parse(("end_tab_shell_body",))
    parser.delete_first_token()
    return TabShellBodyNode(nodelist, attrs)


class TabShellNode(template.Node):
    def __init__(
        self, nodelist: template.NodeList, tabs_partial: FilterExpression
    ) -> None:
        self.nodelist = nodelist
        self.tabs_partial = tabs_partial

    def render(self, context: template.Context) -> str:
        context_data = {str(key): value for key, value in context.flatten().items()}
        context_data.update(
            {
                "tabs_partial": self.tabs_partial.resolve(context),
                "content": self.nodelist.render(context),
            }
        )
        return render_to_string("components/tab-shell.html", context_data)


@register.tag
def tab_shell(parser: Parser, token: Token) -> TabShellNode:
    bits = token.split_contents()
    if len(bits) != _TAB_SHELL_TOKEN_LENGTH:
        msg = "'tab_shell' tag requires exactly one tabs partial"
        raise template.TemplateSyntaxError(msg)
    nodelist = parser.parse(("end_tab_shell",))
    parser.delete_first_token()
    return TabShellNode(nodelist, parser.compile_filter(bits[1]))
