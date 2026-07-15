"""Button renderer."""

from __future__ import annotations

from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .icon import icon as render_icon

_SIZE_CLASSES = {
    "sm": "px-3 py-1.5 text-xs gap-1.5 rounded-xl",
    "md": "px-4 py-2 text-sm",
    "lg": "px-6 py-3 text-base",
}
_ICON_SIZE_CLASSES = {"sm": "w-3.5 h-3.5", "md": "w-4 h-4", "lg": "w-5 h-5"}
_VARIANT_CLASSES = {
    "primary": "btn btn-primary",
    "secondary": "btn btn-secondary",
    "danger": "btn btn-danger",
}


def render_button(  # noqa: PLR0913 — template-tag adapter; each param is a distinct visual axis
    text: str,
    *,
    href: str | None = None,
    button_type: str = "submit",
    variant: str = "primary",
    size: str = "md",
    disabled: bool = False,
    icon: str | None = None,
    full_width_mobile: bool | None = None,
    onclick: str | None = None,
    title: str | None = None,
) -> str:
    """Render a styled button (``<button>``) or link button (``<a>``).

    When ``href`` is set, renders an ``<a>``. When ``icon`` is set, the
    heroicon is rendered before the text.

    ``full_width_mobile`` controls the ``max-md:w-full`` utility — useful for
    form-submit buttons that should stretch on mobile but rarely desired for
    link buttons in toolbars. Defaults to ``href is None``: form-submit
    buttons stretch, link buttons don't.

    ``title`` renders a native tooltip — mainly for explaining *why* a
    disabled button is disabled.

    Returns:
        HTML string of the rendered button.
    """
    if full_width_mobile is None:
        full_width_mobile = href is None
    classes = [
        _VARIANT_CLASSES.get(variant, _VARIANT_CLASSES["primary"]),
        _SIZE_CLASSES.get(size, _SIZE_CLASSES["md"]),
    ]
    if full_width_mobile:
        classes.append("max-md:w-full")
    if disabled:
        classes.append("opacity-50 cursor-not-allowed")
    class_str = " ".join(classes)

    icon_html = (
        render_icon(
            icon, **{"class": _ICON_SIZE_CLASSES.get(size, _ICON_SIZE_CLASSES["md"])}
        )
        if icon
        else ""
    )
    body = format_html("{}{}", mark_safe(icon_html), text)  # noqa: S308
    title_attr = format_html(' title="{}"', title) if title is not None else ""

    if href is not None:
        if disabled:
            return format_html(
                '<a class="{}" aria-disabled="true" tabindex="-1"{}>{}</a>',
                class_str,
                title_attr,
                body,
            )
        return format_html(
            '<a href="{}" class="{}"{}>{}</a>', href, class_str, title_attr, body
        )

    if disabled:
        return format_html(
            '<button type="{}" class="{}" disabled{}>{}</button>',
            button_type,
            class_str,
            title_attr,
            body,
        )
    if onclick is not None:
        return format_html(
            '<button type="{}" class="{}" onclick="{}"{}>{}</button>',
            button_type,
            class_str,
            onclick,
            title_attr,
            body,
        )
    return format_html(
        '<button type="{}" class="{}"{}>{}</button>',
        button_type,
        class_str,
        title_attr,
        body,
    )
