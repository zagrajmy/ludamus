"""{% tessera_switcher %} / {% tessera_segment %} — a segmented radio control.

A generic, Tailwind-styled segmented control modelled on the theme switcher's
look. The selected segment is highlighted purely with ``peer-checked`` — no
JavaScript. Consumers wire behaviour (persistence, navigation) themselves; the
theme switcher is one such use case.

{% tessera_choice_buttons %} / {% tessera_choice_button %} — the same look
for a choice that takes effect at once: each segment is a submit button of
the surrounding form, and ``aria-pressed`` marks the current one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django import template
from django.utils.html import format_html
from django.utils.safestring import SafeString

from ._registry import register
from ._utils import format_tag_attrs, parse_tag_attrs
from .icon import icon as render_icon

if TYPE_CHECKING:
    from django.template.base import FilterExpression, Parser, Token

_FIELDSET_CLASS = "inline-flex items-center gap-0.5 rounded-lg p-0.5 bg-bg-tertiary"
_SEGMENT_CLASS = (
    "flex items-center justify-center w-8 h-8 rounded-md cursor-pointer"
    " text-foreground-muted transition-colors peer-hover:text-foreground"
    " peer-checked:bg-bg-secondary peer-checked:text-foreground"
    " peer-checked:shadow-sm peer-focus-visible:outline-2"
    " peer-focus-visible:outline-offset-2 peer-focus-visible:outline-primary"
)

_NAME_KEY = "_switcher_name"
_SELECTED_KEY = "_switcher_selected"


class SwitcherNode(template.Node):
    """Renders a ``<fieldset>`` radio group wrapping segment children."""

    def __init__(
        self, nodelist: template.NodeList, attrs: dict[str, FilterExpression]
    ) -> None:
        self.nodelist = nodelist
        self.attrs = attrs

    def render(self, context: template.Context) -> str:
        resolved = {k: v.resolve(context) for k, v in self.attrs.items()}
        if not (name := resolved.get("name")):
            msg = "'tessera_switcher' requires a name"
            raise template.TemplateSyntaxError(msg)
        name = str(name)
        selected = resolved.get("selected")
        aria_label = resolved.get("aria_label")

        with context.push(
            **{
                _NAME_KEY: name,
                _SELECTED_KEY: None if selected is None else str(selected),
            }
        ):
            inner = self.nodelist.render(context)

        aria_attr = format_html(' aria-label="{}"', aria_label) if aria_label else ""
        return format_html(
            '<fieldset class="{}" role="radiogroup"{}>{}</fieldset>',
            _FIELDSET_CLASS,
            aria_attr,
            inner,
        )


@register.tag("tessera_switcher")
def tessera_switcher(parser: Parser, token: Token) -> SwitcherNode:
    """Parse a ``{% tessera_switcher %}...{% end_tessera_switcher %}`` block.

    Returns:
        A SwitcherNode rendering a themed segmented radio group.
    """
    attrs = parse_tag_attrs(parser, token)
    nodelist = parser.parse(("end_tessera_switcher",))
    parser.delete_first_token()
    return SwitcherNode(nodelist, attrs)


_MIN_SEGMENT_BITS = 2


class SegmentNode(template.Node):
    """Renders one radio segment; reads name/selected from the switcher."""

    def __init__(
        self,
        *,
        nodelist: template.NodeList,
        value: FilterExpression,
        attrs: dict[str, FilterExpression],
    ) -> None:
        self.nodelist = nodelist
        self.value = value
        self.attrs = attrs

    def render(self, context: template.Context) -> str:
        resolved = {k: v.resolve(context) for k, v in self.attrs.items()}
        value = str(self.value.resolve(context))
        if (name := context.get(_NAME_KEY)) is None:
            msg = "'tessera_segment' must be used inside 'tessera_switcher'"
            raise template.TemplateSyntaxError(msg)
        name = str(name)
        checked = context.get(_SELECTED_KEY) == value
        seg_icon = resolved.get("icon")
        title = resolved.get("title")
        label = self.nodelist.render(context)

        icon_html = (
            render_icon(str(seg_icon), **{"class": "w-4 h-4"}) if seg_icon else ""
        )
        title_attr = format_html(' title="{}"', title) if title else ""
        checked_attr = SafeString(" checked") if checked else ""

        return format_html(
            '<label class="relative"{}>'
            '<input type="radio" name="{}" value="{}" id="{}-{}"'
            ' class="sr-only peer"{}>'
            '<span class="{}"><span class="sr-only">{}</span>{}</span>'
            "</label>",
            title_attr,
            name,
            value,
            name,
            value,
            checked_attr,
            _SEGMENT_CLASS,
            label,
            icon_html,
        )


@register.tag("tessera_segment")
def tessera_segment(parser: Parser, token: Token) -> SegmentNode:
    """Parse a ``{% tessera_segment "value" %}...{% end_tessera_segment %}`` block.

    Returns:
        A SegmentNode rendering one radio segment of a switcher.

    Raises:
        TemplateSyntaxError: If the value argument is missing.
    """
    bits = token.split_contents()
    if len(bits) < _MIN_SEGMENT_BITS:
        msg = f"'{bits[0]}' tag requires at least a value argument"
        raise template.TemplateSyntaxError(msg)

    value = parser.compile_filter(bits[1])
    attrs: dict[str, FilterExpression] = {}
    for bit in bits[2:]:
        key, _, raw = bit.partition("=")
        attrs[key] = parser.compile_filter(raw)

    nodelist = parser.parse(("end_tessera_segment",))
    parser.delete_first_token()
    return SegmentNode(nodelist=nodelist, value=value, attrs=attrs)


_CHOICE_BUTTON_CLASS = (
    "flex items-center gap-1.5 h-8 px-3 rounded-md text-sm font-medium"
    " cursor-pointer text-foreground-muted transition-colors"
    " hover:text-foreground aria-pressed:bg-bg-secondary"
    " aria-pressed:text-foreground aria-pressed:shadow-sm"
    " focus-visible:outline-2 focus-visible:outline-offset-2"
    " focus-visible:outline-primary"
)


class ChoiceButtonsNode(template.Node):
    """Renders the track that holds choice buttons."""

    def __init__(
        self, nodelist: template.NodeList, attrs: dict[str, FilterExpression]
    ) -> None:
        self.nodelist = nodelist
        self.attrs = attrs

    def render(self, context: template.Context) -> str:
        resolved = {k: v.resolve(context) for k, v in self.attrs.items()}
        if not (name := resolved.get("name")):
            msg = "'tessera_choice_buttons' requires a name"
            raise template.TemplateSyntaxError(msg)
        selected = resolved.get("selected")
        with context.push(
            **{
                _NAME_KEY: str(name),
                _SELECTED_KEY: None if selected is None else str(selected),
            }
        ):
            inner = self.nodelist.render(context)
        return format_html(
            '<div class="{}">{}</div>', _FIELDSET_CLASS, SafeString(inner)
        )


@register.tag("tessera_choice_buttons")
def tessera_choice_buttons(parser: Parser, token: Token) -> ChoiceButtonsNode:
    """Parse ``{% tessera_choice_buttons name=… selected=… %}`` and its end tag.

    The group's label comes from the surrounding ``<fieldset>`` and legend.

    Returns:
        A ChoiceButtonsNode rendering the segmented track.
    """
    attrs = parse_tag_attrs(parser, token)
    nodelist = parser.parse(("end_tessera_choice_buttons",))
    parser.delete_first_token()
    return ChoiceButtonsNode(nodelist, attrs)


class ChoiceButtonNode(template.Node):
    """Renders one submit button; reads name/selected from the group."""

    def __init__(
        self,
        *,
        nodelist: template.NodeList,
        value: FilterExpression,
        attrs: dict[str, FilterExpression],
    ) -> None:
        self.nodelist = nodelist
        self.value = value
        self.attrs = attrs

    def render(self, context: template.Context) -> str:
        if (name := context.get(_NAME_KEY)) is None:
            msg = "'tessera_choice_button' must be used inside 'tessera_choice_buttons'"
            raise template.TemplateSyntaxError(msg)
        value = str(self.value.resolve(context))
        resolved = {k: v.resolve(context) for k, v in self.attrs.items()}
        return format_html(
            '<button type="submit" name="{}" value="{}" class="{}"'
            ' aria-pressed="{}" {}>{}</button>',
            name,
            value,
            _CHOICE_BUTTON_CLASS,
            "true" if context.get(_SELECTED_KEY) == value else "false",
            format_tag_attrs(resolved),
            SafeString(self.nodelist.render(context)),
        )


@register.tag("tessera_choice_button")
def tessera_choice_button(parser: Parser, token: Token) -> ChoiceButtonNode:
    """Parse ``{% tessera_choice_button "value" %}…{% end_tessera_choice_button %}``.

    Keywords after the value (``lang``, ``aria_*``, ``data_*``) become
    attributes of the button.

    Returns:
        A ChoiceButtonNode rendering one choice of the group.

    Raises:
        TemplateSyntaxError: If the value argument is missing.
    """
    bits = token.split_contents()
    if len(bits) < _MIN_SEGMENT_BITS:
        msg = f"'{bits[0]}' tag requires at least a value argument"
        raise template.TemplateSyntaxError(msg)
    attrs: dict[str, FilterExpression] = {}
    for bit in bits[2:]:
        key, _, raw = bit.partition("=")
        attrs[key] = parser.compile_filter(raw)
    nodelist = parser.parse(("end_tessera_choice_button",))
    parser.delete_first_token()
    return ChoiceButtonNode(
        nodelist=nodelist, value=parser.compile_filter(bits[1]), attrs=attrs
    )
