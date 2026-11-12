"""{% tessera_icon_button %} — an action whose whole label is its icon."""

from __future__ import annotations

from django.utils.html import format_html, format_html_join

from ._registry import register
from .icon import icon as render_icon

# Deliberately not `.btn`: a text button is a pill that asks to be pressed,
# while these sit on top of content they must not compete with — a sheet's
# close control, a dismiss, a remove. Square, because the horizontal padding a
# label needs would leave an icon lopsided without one.
_BASE_CLASS = (
    "inline-flex items-center justify-center shrink-0 rounded-lg cursor-pointer"
    " text-foreground-muted bg-transparent border border-transparent"
    " transition-[color,background-color,opacity] duration-150"
    " hover:text-foreground hover:bg-bg-tertiary"
    " focus-visible:outline-2 focus-visible:outline-offset-2"
    " focus-visible:outline-primary"
    " disabled:opacity-50 disabled:cursor-not-allowed"
)
_SIZE_CLASSES = {"sm": "p-1.5", "md": "p-2", "lg": "p-2.5"}
_ICON_SIZE_CLASSES = {"sm": "w-4 h-4", "md": "w-5 h-5", "lg": "w-6 h-6"}


@register.simple_tag
def tessera_icon_button(
    *,
    icon: str,
    label: str,
    size: str = "md",
    button_type: str = "button",
    variant: str = "mini",
    disabled: bool = False,
    extra_class: str = "",
    **attrs: str | int | bool | None,
) -> str:
    """Render an icon-only button.

    ``label`` is required and becomes the accessible name: an icon cannot
    supply one, and a button no screen reader can announce is not a button.

    Returns:
        HTML string of the rendered icon button.

    Usage:
        {% tessera_icon_button icon="x-mark" label=close_label id="filter-close" %}
        {% tessera_icon_button icon="trash" label=remove_label size="sm" %}
    """
    if not label:
        msg = "tessera_icon_button needs a label: its icon is not a name."
        raise ValueError(msg)

    classes = " ".join(
        part
        for part in (
            _BASE_CLASS,
            _SIZE_CLASSES.get(size, _SIZE_CLASSES["md"]),
            extra_class,
        )
        if part
    )
    rendered_attrs = format_html_join(
        "",
        ' {}="{}"',
        (
            (name.replace("_", "-"), value)
            for name, value in attrs.items()
            if value is not None and value is not False
        ),
    )
    return format_html(
        '<button type="{}" class="{}" aria-label="{}"{}{}>{}</button>',
        button_type,
        classes,
        label,
        " disabled" if disabled else "",
        rendered_attrs,
        render_icon(
            icon,
            variant=variant,
            **{
                "class": _ICON_SIZE_CLASSES.get(size, _ICON_SIZE_CLASSES["md"]),
                "aria_hidden": "true",
            },
        ),
    )
