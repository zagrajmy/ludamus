"""Copy-to-clipboard button with a confirmation popover."""

from __future__ import annotations

from django.utils.html import format_html

from ._registry import register
from .icon import icon as render_icon

# Behavior lives with the markup (no global script). The popover is revealed
# only inside `.then`, so an unavailable clipboard (insecure context, where
# `?.` short-circuits) or a rejected write shows nothing instead of a false
# confirmation. `this` is the button; `this._t` scopes the hide-timer per button
# so rapid clicks reset it instead of stacking. Passed to format_html as an
# escaped argument (not spliced into the template), so braces here are safe.
_ONCLICK = (
    "navigator.clipboard?.writeText(this.dataset.copy)?.then(() => {"
    "const p = this.querySelector('[data-copy-popover]');"
    "p.setAttribute('data-show', '');"
    "clearTimeout(this._t);"
    "this._t = setTimeout(() => p.removeAttribute('data-show'), 1500);"
    "})"
)

# The popover is always in the DOM but absolute + pointer-events-none, so it
# never affects the button's box — the button can't resize on success. It only
# fades/scales in when `data-show` is present; removing the attribute transitions
# it back out. Styled after the graphql-hive docs heading copy-link popover.
_POPOVER_CLASS = (
    "pointer-events-none absolute bottom-full left-1/2 z-10 mb-2 -translate-x-1/2 "
    "whitespace-nowrap rounded-md bg-bg-secondary px-2 py-1 text-xs font-medium "
    "tracking-[0.01em] text-foreground shadow-(--shadow-card) ring-1 ring-border "
    "opacity-0 scale-90 transition duration-150 ease-out "
    "data-[show]:opacity-100 data-[show]:scale-100"
)


@register.simple_tag
def tessera_copy(text: str, *, label: str, copied_label: str) -> str:
    """Render a button that shows ``text``, copies it, and pops a confirmation.

    The whole ``text`` is the clickable target (a larger, clearer control than an
    icon alone); ``label`` is added as visually-hidden text so the button's
    accessible name is e.g. "@ada Copy to clipboard" — the visible text stays
    part of the name (WCAG 2.5.3).

    Returns:
        HTML string of the button and its confirmation popover.

    Usage:
        {% translate "Copy to clipboard" as t_label %}
        {% translate "Copied!" as t_copied %}
        {% tessera_copy "@ada" label=t_label copied_label=t_copied %}
    """
    # render_icon returns a SafeString; every other value is a plain str, so
    # format_html escapes the caller's data and the trusted-but-untagged
    # constants alike. Entities in the escaped handler decode back to JS in the
    # attribute, so the onclick still runs. The icon renders aria-hidden, so the
    # sr-only label (not the glyph) carries the copy intent for screen readers.
    icon_html = render_icon(
        "clipboard", variant="outline", **{"class": "size-4 text-foreground-muted"}
    )
    return format_html(
        '<button type="button" class="icon-btn gap-1.5 px-2 py-1 text-sm"'
        ' data-copy="{copy}" title="{label}" onclick="{onclick}">'
        '<code class="text-foreground [text-box:trim-both_cap_alphabetic]">'
        "{display}</code>"
        "{icon}"
        '<span class="sr-only">{label}</span>'
        '<span aria-hidden="true" data-copy-popover class="{popover}">{copied}</span>'
        "</button>",
        copy=text,
        display=text,
        label=label,
        onclick=_ONCLICK,
        icon=icon_html,
        popover=_POPOVER_CLASS,
        copied=copied_label,
    )
