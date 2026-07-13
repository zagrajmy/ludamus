"""{% tab_shell_body %} / {% end_tab_shell %} — tab shell layout wrappers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django import template
from django.template.loader import render_to_string
from django.utils.html import format_html
from django.utils.safestring import SafeString

from ._registry import register
from ._utils import parse_tag_attrs

if TYPE_CHECKING:
    from django.template.base import FilterExpression, Parser, Token


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
                "content": SafeString(self.nodelist.render(context)),
            },
        )


@register.tag
def tab_shell_body(parser: Parser, token: Token) -> TabShellBodyNode:
    attrs = parse_tag_attrs(parser, token)
    nodelist = parser.parse(("end_tab_shell_body",))
    parser.delete_first_token()
    return TabShellBodyNode(nodelist, attrs)


@register.simple_tag(takes_context=True)
def tab_shell(context: template.Context, tabs_partial: str) -> str:
    context_data = {str(key): value for key, value in context.flatten().items()}
    context_data["tabs_partial"] = tabs_partial
    rendered_bar = render_to_string("components/tab-shell-bar.html", context_data)
    return format_html('<div class="overflow-hidden">{}', rendered_bar)


@register.simple_tag
def end_tab_shell() -> str:
    return SafeString("</div>")
