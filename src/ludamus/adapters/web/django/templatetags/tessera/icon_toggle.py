"""{% icon_toggle %} — binary icon toggle button (Tailwind-styled)."""

from __future__ import annotations

from django.utils.html import format_html, format_html_join

from ._registry import register
from .icon import icon as render_icon

# Pill-shaped toggle, distinct from the square .icon-btn. State is the standard
# aria-pressed; the on/off icons swap via the group-aria-pressed variant, so no
# bespoke CSS is needed.
_BUTTON_CLASS = (
    "group inline-flex items-center justify-center p-1.5 rounded-full cursor-pointer"
    " bg-bg-tertiary text-foreground-muted transition-colors hover:text-foreground"
    " focus-visible:outline-2 focus-visible:outline-offset-2"
    " focus-visible:outline-primary aria-pressed:text-primary"
    " aria-pressed:bg-primary-light dark:aria-pressed:bg-transparent"
    " aria-pressed:ring-[1.5px] aria-pressed:ring-inset aria-pressed:ring-primary"
)
_ON_ICON_CLASS = "w-4 h-4 hidden group-aria-pressed:block"
_OFF_ICON_CLASS = "w-4 h-4 group-aria-pressed:hidden"


def _data_attrs(attrs: dict[str, object]) -> str:
    # ``data_velvet_toggle=True`` -> ``data-velvet-toggle``; a value renders
    # ``name="value"``. Only ``data_*`` extras are allowed, so a typo can't
    # leak ``class``/``aria_label`` onto the button. format_html escapes values;
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
    pressed: bool = False,
    **attrs: object,
) -> str:
    """Render a binary icon toggle button.

    Shows ``off_icon`` until ``aria-pressed`` is ``"true"``, then ``on_icon``.
    Extra ``data_*`` keyword arguments become ``data-*`` attributes.

    Returns:
        HTML string of the toggle button.

    Usage:
        {% tessera_icon_toggle on_icon="speaker-wave" off_icon="speaker-x-mark"
            label=toggle_label data_velvet_toggle=True %}
    """
    on_html = render_icon(on_icon, **{"class": _ON_ICON_CLASS})
    off_html = render_icon(off_icon, **{"class": _OFF_ICON_CLASS})
    title_attr = format_html(' title="{}"', title) if title else ""
    return format_html(
        '<button type="button" class="{}" aria-pressed="{}"{}{}>'
        '<span class="sr-only">{}</span>{}{}</button>',
        _BUTTON_CLASS,
        "true" if pressed else "false",
        title_attr,
        _data_attrs(attrs),
        label,
        on_html,
        off_html,
    )
