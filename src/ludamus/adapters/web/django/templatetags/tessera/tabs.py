"""{% tabs %} / {% tab %} template tags — navigation tab components."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

from ._registry import register
from ._utils import parse_tag_attrs
from .icon import icon

if TYPE_CHECKING:
    from django.template.base import FilterExpression, Parser, Token

TAB_NAV_CLASS = "inline-flex gap-1 items-end"
_TAB_BASE = (
    "inline-flex items-center gap-1.5 px-4 text-sm font-medium"
    " rounded-t-lg transition-colors"
)
TAB_ACTIVE_CLASS = (
    f"{_TAB_BASE} py-2.5 bg-bg-secondary text-primary"
    " -mb-px relative z-10 shadow-[0_-1px_3px_0_rgba(0,0,0,0.06)]"
)
TAB_INACTIVE_CLASS = (
    f"{_TAB_BASE} py-2 text-foreground-muted hover:text-foreground"
    " hover:bg-warm-100 dark:hover:bg-bg-tertiary"
)


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
        extra_class = resolved.pop("class", "")
        aria_label = resolved.pop("aria_label", None)
        classes = (
            f"{TAB_NAV_CLASS} {extra_class}".strip() if extra_class else TAB_NAV_CLASS
        )
        aria_attr = f' aria-label="{escape(str(aria_label))}"' if aria_label else ""
        inner = self.nodelist.render(context)
        return mark_safe(  # noqa: S308
            f'<nav class="{classes}" role="tablist"{aria_attr}>{inner}</nav>'
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
        active = bool(resolved.pop("active", False))
        tab_icon = resolved.pop("icon", None)
        href = resolved.pop("href", "#")

        classes = TAB_ACTIVE_CLASS if active else TAB_INACTIVE_CLASS
        label = self.nodelist.render(context)

        icon_html = ""
        if tab_icon:
            icon_html = icon(str(tab_icon), **{"class": "w-4 h-4"})

        return mark_safe(  # noqa: S308
            f'<a class="{classes}" role="tab"'
            f' aria-selected="{"true" if active else "false"}"'
            f' href="{escape(str(href))}">{icon_html}{label}</a>'
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
