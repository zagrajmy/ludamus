"""Copy-to-clipboard button with a confirmation popover.

The click behaviour is wired once in ``src/copy.ts`` (a delegated listener on
``[data-copy]``); the tags here emit declarative markup only.
"""

from __future__ import annotations

from django.template import TemplateSyntaxError
from django.utils.html import format_html
from django.utils.translation import gettext

from ._registry import register
from .clsx import clsx
from .icon import icon as render_icon

# The popover is always in the DOM but absolute + pointer-events-none, so it
# never affects the button's box — the button can't resize on success. copy.ts
# writes its label and toggles `data-show` on a successful copy; the CSS fades /
# scales it in. It's an aria-live region so screen readers hear the confirmation.
# Styled after the graphql-hive docs heading copy-link popover.
_POPOVER_CLASS = (
    "pointer-events-none absolute bottom-full left-1/2 z-10 mb-2 -translate-x-1/2 "
    "whitespace-nowrap rounded-md bg-bg-secondary px-2 py-1 text-xs font-medium "
    "tracking-[0.01em] text-foreground shadow-(--shadow-card) ring-1 ring-border "
    "opacity-0 scale-90 transition duration-150 ease-out "
    "data-[show]:opacity-100 data-[show]:scale-100"
)


@register.simple_tag
def tessera_copy_popover() -> str:
    """Render the copy-confirmation popover for a ``[data-copy]`` button.

    Drop it inside any copy button (which must be ``position: relative`` — the
    ``.btn`` / ``.icon-btn`` styles already are) that carries ``data-copy`` and
    ``data-copied-label``; ``copy.ts`` fills and reveals it on a successful copy.

    Returns:
        HTML string of the (initially empty) popover span.
    """
    return format_html(
        '<span role="status" aria-live="polite" data-copy-popover class="{}"></span>',
        _POPOVER_CLASS,
    )


# The looks live here, not at the callsites: a copy control is either a regular
# secondary button or a row in a dropdown menu. `relative` anchors the popover.
_VARIANT_CLASSES = {
    "button": "btn btn-secondary text-sm w-full",
    "menu-item": (
        "relative w-full px-3 py-2 text-sm text-left text-foreground "
        "hover:bg-bg-tertiary focus-visible:bg-bg-tertiary"
    ),
}


@register.simple_block_tag
def tessera_copy(
    content: str,
    copy: str,
    *,
    variant: str = "button",
    copied_label: str = "",
    origin: bool = False,
    **kwargs: object,
) -> str:
    """Wrap icon/label markup in a button that copies ``copy`` on click.

    The component owns the look — pick a ``variant`` ("button" or "menu-item");
    the block provides only the icon and label. ``class`` may add layout-only
    utilities (e.g. a menu row's corner rounding). ``origin=True`` prefixes the
    current origin, for host-agnostic share paths. The click behaviour and the
    confirmation popover come from ``copy.ts``.

    Returns:
        HTML string of the button wrapping ``content`` plus the popover.

    Raises:
        TemplateSyntaxError: On unknown keyword arguments (likely typos).

    Usage:
        {% tessera_copy share_url %}
            {% icon "clipboard-document" variant="solid" class="h-4 w-4" %}
            {% translate "Copy link" %}
        {% endtessera_copy %}
    """
    copied_label = copied_label or gettext("Copied!")
    # **kwargs exists only because `class` is a reserved word; anything else is
    # a typo (e.g. copied_lable=) and must not vanish silently.
    classes = clsx(_VARIANT_CLASSES[variant], kwargs.pop("class", None))
    if kwargs:
        msg = f"tessera_copy got unknown arguments: {sorted(kwargs)}"
        raise TemplateSyntaxError(msg)
    origin_attr = " data-copy-origin" if origin else ""
    return format_html(
        '<button type="button" class="{classes}" data-copy="{copy}"'
        '{origin} data-copied-label="{copied}">{content}{popover}</button>',
        classes=classes,
        copy=copy,
        origin=origin_attr,
        copied=copied_label,
        content=content,
        popover=tessera_copy_popover(),
    )


@register.simple_tag
def copy_lines(*parts: object) -> str:
    """Join non-empty ``parts`` with newlines — a copy payload for ``tessera_copy``.

    Returns:
        The parts (skipping empties) joined by newlines.
    """
    return "\n".join(str(p) for p in parts if p)


@register.simple_tag
def tessera_copy_chip(text: str, *, label: str = "", copied_label: str = "") -> str:
    """Render a chip that shows ``text``, copies it, and pops a confirmation.

    The chip preset for the common "copy this short value" case: the whole
    ``text`` is the clickable target (a larger, clearer control than an icon
    alone); ``label`` is added as visually-hidden text so the button's accessible
    name is e.g. "@ada Copy to clipboard" — the visible text stays part of the
    name (WCAG 2.5.3). ``label`` and ``copied_label`` default to the translated
    "Copy to clipboard" / "Copied!", so callers rarely pass them.

    For buttons with their own look (full-width, menu rows), keep the markup and
    opt into the behaviour with ``data-copy`` + ``{% tessera_copy_popover %}``.

    Returns:
        HTML string of the button and its confirmation popover.

    Usage:
        {% tessera_copy_chip "@ada" %}
    """
    label = label or gettext("Copy to clipboard")
    copied_label = copied_label or gettext("Copied!")
    # render_icon returns a SafeString and tessera_copy_popover() a safe span, so
    # format_html escapes only the caller's data (text/label/copied_label). The
    # icon renders aria-hidden, so the sr-only label carries the intent for
    # screen readers.
    icon_html = render_icon(
        "clipboard", variant="outline", **{"class": "size-4 text-foreground-muted"}
    )
    return format_html(
        '<button type="button" class="icon-btn gap-1.5 px-2 py-1 text-sm"'
        ' data-copy="{copy}" data-copied-label="{copied}" title="{label}">'
        '<code class="text-foreground [text-box:trim-both_cap_alphabetic]">'
        "{display}</code>"
        "{icon}"
        '<span class="sr-only">{label}</span>'
        "{popover}"
        "</button>",
        copy=text,
        display=text,
        label=label,
        icon=icon_html,
        popover=tessera_copy_popover(),
        copied=copied_label,
    )
