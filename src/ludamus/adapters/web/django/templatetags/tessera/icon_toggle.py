"""{% icon_toggle %} — binary icon toggle (hidden checkbox, Tailwind-styled)."""

from __future__ import annotations

from django.utils.html import format_html, format_html_join

from ._registry import register
from .icon import icon as render_icon

_LABEL_CLASS = (
    "group inline-flex items-center justify-center p-1.5 rounded-full cursor-pointer"
    " bg-bg-tertiary text-foreground-muted transition-colors hover:text-foreground"
    " border border-transparent hover:border-border has-checked:text-foreground"
    " has-focus-visible:outline-2 has-focus-visible:outline-offset-2"
    " has-focus-visible:outline-primary"
)
_ON_ICON_CLASS = "w-4 h-4 hidden peer-checked:block"
_OFF_ICON_CLASS = "w-4 h-4 peer-checked:hidden"


def _data_attrs(attrs: dict[str, object]) -> str:
    # ``name="value"``. Only ``data_*`` extras are allowed, so a typo can't
    # bare names are Python identifiers, so escaping them is a no-op.
    pairs = []
    for key, value in attrs.items():
        if not key.startswith("data_"):
            msg = f"icon_toggle only accepts data_* extra attrs, got {key!r}"
            raise ValueError(msg)
        name = key.replace("_", "-")
        if value is True:
            pairs.append((name,))
        elif value not in {False, None}:
            pairs.append((format_html('{}="{}"', name, value),))
    return format_html_join("", " {}", pairs)


@register.simple_tag
def tessera_icon_toggle(
    *,
    on_icon: str,
    off_icon: str,
    label: str,
    title: str | None = None,
    checked: bool = False,
    **attrs: object,
) -> str:
    """Render a binary icon toggle backed by a visually hidden checkbox.

    Shows ``off_icon`` until the checkbox is checked, then ``on_icon``.
    Extra ``data_*`` keyword arguments become ``data-*`` attributes on the
    checkbox input.

    Returns:
        HTML string of the toggle.

    Usage:
        {% tessera_icon_toggle on_icon="speaker-wave" off_icon="speaker-x-mark"
            label=toggle_label data_sound_toggle=True %}
    """
    on_html = render_icon(on_icon, **{"class": _ON_ICON_CLASS})
    off_html = render_icon(off_icon, **{"class": _OFF_ICON_CLASS})
    title_attr = format_html(' title="{}"', title) if title else ""
    return format_html(
        '<label class="{}"{}>'
        '<input type="checkbox" class="peer sr-only"{}{}>'
        '<span class="sr-only">{}</span>{}{}</label>',
        _LABEL_CLASS,
        title_attr,
        " checked" if checked else "",
        _data_attrs(attrs),
        label,
        on_html,
        off_html,
    )
