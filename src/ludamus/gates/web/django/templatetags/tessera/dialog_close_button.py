"""{% tessera_dialog_close_button %} — the × in a modal dialog's header."""

from __future__ import annotations

from django.utils.html import format_html
from django.utils.translation import gettext as _

from ._registry import register
from .icon import icon as render_icon

# A bare white icon for a dark picture, such as a session cover. The shadow
# keeps it legible on a light photo, which no fixed colour could.
_ON_COVER_CLASS = (
    " text-white hover:text-white hover:bg-white/15"
    " drop-shadow-[0_1px_2px_rgba(0,0,0,0.7)]"
)


@register.simple_tag
def tessera_dialog_close_button(dialog_id: str, *, on_cover: bool = False) -> str:
    """Render the clear icon button that closes the dialog named ``dialog_id``.

    `modal.ts` closes the dialog a ``data-modal-close`` button names, and
    clears that dialog's query parameter from the address. The button is a
    44px square, a full touch target, around a 20px icon. ``on_cover`` draws
    it white, for a button that sits on a cover picture.

    Returns:
        HTML string of the close button.

    Usage:
        {% tessera_dialog_close_button "organize-modal" %}
        {% tessera_dialog_close_button "session-1" on_cover=True %}
    """
    return format_html(
        '<button type="button"'
        ' class="icon-btn icon-btn-clear size-11 shrink-0 justify-center{}"'
        ' data-modal-close="{}" aria-label="{}">{}</button>',
        _ON_COVER_CLASS if on_cover else "",
        dialog_id,
        _("Close"),
        render_icon("x-mark", **{"class": "w-5 h-5", "aria_hidden": "true"}),
    )
