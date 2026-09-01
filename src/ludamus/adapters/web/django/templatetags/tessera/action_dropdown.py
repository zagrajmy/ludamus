"""{% tessera_action_dropdown %} — a trigger opening a small menu of actions.

Wired to the shared disclosure-menu behavior (menu.ts): click or hover to
open, Esc and click-outside to close, live aria-expanded.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django import template
from django.template.loader import render_to_string
from django.utils.html import format_html

from ._registry import register
from ._utils import format_tag_attrs, parse_tag_attrs
from .button import SIZE_CLASSES, VARIANT_CLASSES
from .icon import icon as render_icon

if TYPE_CHECKING:
    from django.template.base import FilterExpression, NodeList, Parser, Token
    from django.template.context import Context

_ALIGN_CLASSES = {
    "start": "left-0",
    "center": "left-1/2 -translate-x-1/2",
    "end": "right-0",
}

_TRIGGER_VARIANTS = {
    "plain": "rounded-lg",
    "secondary": f"{VARIANT_CLASSES['secondary']} {SIZE_CLASSES['md']}",
}

_ITEM_CLASS = (
    "flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium"
    " whitespace-nowrap cursor-pointer text-foreground-secondary"
    " transition-colors duration-150 hover:bg-bg-tertiary hover:text-foreground"
    " focus-visible:outline-2 focus-visible:outline-primary"
)


class ActionDropdownNode(template.Node):
    _TEMPLATE = "components/action-dropdown.html"

    def __init__(
        self, trigger: NodeList, items: NodeList, attrs: dict[str, FilterExpression]
    ) -> None:
        self.trigger = trigger
        self.items = items
        self.attrs = attrs

    def render(self, context: Context) -> str:
        resolved = {key: value.resolve(context) for key, value in self.attrs.items()}
        if not (element_id := str(resolved.pop("id", "") or "")):
            msg = "tessera_action_dropdown needs an id for aria-controls."
            raise template.TemplateSyntaxError(msg)
        if (align := str(resolved.pop("align", "start"))) not in _ALIGN_CLASSES:
            options = sorted(_ALIGN_CLASSES)
            msg = f"tessera_action_dropdown align must be one of {options}"
            raise template.TemplateSyntaxError(msg)
        hover = bool(resolved.pop("hover", True))
        label = str(resolved.pop("label", "") or "")
        variant = str(resolved.pop("trigger_variant", "plain"))
        if variant not in _TRIGGER_VARIANTS:
            options = sorted(_TRIGGER_VARIANTS)
            msg = f"tessera_action_dropdown trigger_variant must be one of {options}"
            raise template.TemplateSyntaxError(msg)
        extra_class = str(resolved.pop("trigger_class", "") or "")
        trigger_class = " ".join(
            part for part in (_TRIGGER_VARIANTS[variant], extra_class) if part
        )

        return render_to_string(
            self._TEMPLATE,
            {
                "align_class": _ALIGN_CLASSES[align],
                "attrs": format_tag_attrs(resolved),
                "hover": hover,
                "id": element_id,
                "items": self.items.render(context),
                "label": label,
                "trigger": self.trigger.render(context),
                "trigger_class": trigger_class,
            },
        )


@register.tag("tessera_action_dropdown")
def do_action_dropdown(parser: Parser, token: Token) -> ActionDropdownNode:
    """Parse the dropdown's two slots: trigger content, then menu items.

    ``trigger_variant`` picks the trigger's look from the button system:
    ``plain`` is a bare trigger, ``secondary`` wears the secondary button.
    ``trigger_class`` adds layout on top of it, never a look of its own.

    Returns:
        An ActionDropdownNode rendering the trigger button plus its menu.

    Usage:
        {% tessera_action_dropdown id="cal-menu" label=t_menu align="center" %}
            ...trigger content...
        {% action_dropdown_menu %}
            {% tessera_action_dropdown_item t_gcal href=gcal_url external=True %}
            {% tessera_action_dropdown_item t_ics href=ics_url icon="arrow-down-tray" %}
        {% endtessera_action_dropdown %}
    """
    attrs = parse_tag_attrs(parser, token)
    trigger = parser.parse(("action_dropdown_menu",))
    parser.delete_first_token()
    items = parser.parse(("endtessera_action_dropdown",))
    parser.delete_first_token()
    return ActionDropdownNode(trigger, items, attrs)


@register.simple_tag
def tessera_action_dropdown_item(
    text: str,
    *,
    href: str = "",
    form: str = "",
    icon: str = "",
    external: bool = False,
    **attrs: str | int | bool | None,
) -> str:
    """Render one navigation or submit row in an action dropdown.

    Give the item exactly one destination: ``href`` renders a link, while
    ``form`` renders a submit button associated with that form's id.
    ``external`` marks links that open in a new tab.

    Returns:
        HTML string of the rendered menu item.
    """
    if bool(href) == bool(form):
        msg = "tessera_action_dropdown_item needs exactly one of href or form."
        raise template.TemplateSyntaxError(msg)
    if external and form:
        msg = "tessera_action_dropdown_item external is only valid with href."
        raise template.TemplateSyntaxError(msg)
    leading = (
        format_html(
            '<span aria-hidden="true" class="shrink-0 opacity-60">{}</span>',
            render_icon(icon, variant="mini", **{"class": "w-4 h-4"}),
        )
        if icon
        else ""
    )
    trailing_wrap = (
        '<span aria-hidden="true" class="shrink-0 ml-auto pl-3 opacity-40">{}</span>'
    )
    trailing = (
        format_html(
            trailing_wrap,
            render_icon(
                "arrow-top-right-on-square", variant="micro", **{"class": "w-3.5 h-3.5"}
            ),
        )
        if external
        else ""
    )
    extra_attrs = format_html(" {}", format_tag_attrs(attrs)) if attrs else ""
    if form:
        return format_html(
            '<button type="submit" form="{}" class="{} w-full text-left"{}>'
            "{}<span>{}</span></button>",
            form,
            _ITEM_CLASS,
            extra_attrs,
            leading,
            text,
        )

    external_attrs = (
        format_html(' target="_blank" rel="{}"', "noopener") if external else ""
    )
    return format_html(
        '<a href="{}" class="{}"{}{}>{}<span>{}</span>{}</a>',
        href,
        _ITEM_CLASS,
        external_attrs,
        extra_attrs,
        leading,
        text,
        trailing,
    )
