"""{% tabs %} / {% tab %} template tags — navigation tab components."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django import template
from django.template.loader import render_to_string

from ._registry import register
from ._utils import parse_tag_attrs

if TYPE_CHECKING:
    from django.template.base import FilterExpression, Parser, Token


class TabsNode(template.Node):
    """Renders a ``<nav>`` tab list wrapping ``{% tab %}`` children."""

    def __init__(
        self, nodelist: template.NodeList, attrs: dict[str, FilterExpression]
    ) -> None:
        self.nodelist = nodelist
        self.attrs = attrs

    def render(self, context: template.Context) -> str:
        resolved: dict[str, object] = {
            k: v.resolve(context) for k, v in self.attrs.items()
        }
        variant = str(resolved.pop("variant", "") or "")
        with context.push(_tabs_variant=variant):
            tabs = self.nodelist.render(context)
        return render_to_string(
            "components/tab-list.html",
            {
                "extra_class": resolved.pop("class", ""),
                "aria_label": resolved.pop("aria_label", None),
                "variant": variant,
                "tabs": tabs,
            },
        )


@register.tag("tabs")
def do_tabs(parser: Parser, token: Token) -> TabsNode:
    """Parse ``{% tabs %}...{% end_tabs %}``.

    Returns:
        A TabsNode that renders a themed ``<nav>`` wrapping its body.
    """
    attrs = parse_tag_attrs(parser, token)
    nodelist = parser.parse(("end_tabs",))
    parser.delete_first_token()
    return TabsNode(nodelist, attrs)


class TabNode(template.Node):
    """Renders a single ``<a>`` tab trigger."""

    def __init__(
        self,
        nodelist: template.NodeList,
        key: FilterExpression,
        attrs: dict[str, FilterExpression],
    ) -> None:
        self.nodelist = nodelist
        self.key = key
        self.attrs = attrs

    def render(self, context: template.Context) -> str:
        resolved: dict[str, object] = {
            k: v.resolve(context) for k, v in self.attrs.items()
        }
        tab_key = self.key.resolve(context)
        if "active" in resolved:
            active = bool(resolved.pop("active"))
        elif "active_tab" in context:
            active = str(tab_key) == str(context["active_tab"])
        else:
            active = False
        return render_to_string(
            "components/tab-link.html",
            {
                "tab_key": tab_key,
                "active": active,
                "icon": resolved.pop("icon", None),
                "href": resolved.pop("href", "#"),
                "variant": context.get("_tabs_variant", ""),
                "label": self.nodelist.render(context),
            },
        )


_MIN_TAB_BITS = 2


@register.tag("tab")
def do_tab(parser: Parser, token: Token) -> TabNode:
    """Parse ``{% tab "key" ... %} label {% end_tab %}``.

    Returns:
        A TabNode that renders a themed ``<a>`` tab trigger.

    Raises:
        TemplateSyntaxError: If the key argument is missing.
    """
    bits = token.split_contents()
    tag_name = bits[0]
    if len(bits) < _MIN_TAB_BITS:
        msg = f"'{tag_name}' tag requires at least a key argument"
        raise template.TemplateSyntaxError(msg)

    key = parser.compile_filter(bits[1])
    attrs: dict[str, FilterExpression] = {}
    for bit in bits[2:]:
        k, _, v = bit.partition("=")
        attrs[k] = parser.compile_filter(v)

    nodelist = parser.parse(("end_tab",))
    parser.delete_first_token()
    return TabNode(nodelist, key, attrs)
