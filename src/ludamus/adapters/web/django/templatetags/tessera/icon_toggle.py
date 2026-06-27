"""{% icon_toggle %} — binary icon toggle button built on ``.icon-btn``."""

from __future__ import annotations

from django.utils.html import format_html, format_html_join

from ._registry import register
from .icon import icon as render_icon

_ICON_CLASS = "w-4 h-4"


def _data_attrs(attrs: dict[str, object]) -> str:
    # ``data_velvet_toggle=True`` -> ``data-velvet-toggle``; a value renders
    # ``name="value"``. format_html escapes values; bare names are Python
    # identifiers, so escaping them is a no-op.
    pairs = []
    for key, value in attrs.items():
        name = key.replace("_", "-")
        if value is True:
            pairs.append((name,))
        elif value not in {False, None}:
            pairs.append((format_html('{}="{}"', name, value),))
    return format_html_join("", " {}", pairs)


@register.simple_tag
def icon_toggle(
    *,
    on_icon: str,
    off_icon: str,
    label: str,
    title: str | None = None,
    pressed: bool = False,
    **attrs: object,
) -> str:
    """Render a binary icon toggle button.

    Shows ``off_icon`` until ``aria-pressed`` is ``"true"``, then ``on_icon``
    (the swap is CSS-only, keyed on ``aria-pressed``). Extra ``data_*`` keyword
    arguments become ``data-*`` attributes.

    Returns:
        HTML string of the toggle button.

    Usage:
        {% icon_toggle on_icon="speaker-wave" off_icon="speaker-x-mark"
            label=toggle_label data_velvet_toggle=True %}
    """
    on_html = render_icon(on_icon, **{"class": f"{_ICON_CLASS} icon-toggle-on"})
    off_html = render_icon(off_icon, **{"class": f"{_ICON_CLASS} icon-toggle-off"})
    title_attr = format_html(' title="{}"', title) if title else ""
    return format_html(
        '<button type="button" class="icon-toggle" aria-pressed="{}"{}{}>'
        '<span class="sr-only">{}</span>{}{}</button>',
        "true" if pressed else "false",
        title_attr,
        _data_attrs(attrs),
        label,
        on_html,
        off_html,
    )
