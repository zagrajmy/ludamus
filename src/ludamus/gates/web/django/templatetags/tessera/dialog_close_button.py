"""{% tessera_dialog_close_button %} — the × in a modal dialog's header."""

from __future__ import annotations

from django.utils.html import format_html
from django.utils.translation import gettext as _

from ._registry import register
from .icon import icon as render_icon


@register.simple_tag
def tessera_dialog_close_button(dialog_id: str) -> str:
    """Render the clear icon button that closes the dialog named ``dialog_id``.

    `modal.ts` closes the dialog a ``data-modal-close`` button names, and
    clears that dialog's query parameter from the address. The button is a
    44px square, a full touch target, around a 20px icon.

    Returns:
        HTML string of the close button.

    Usage:
        {% tessera_dialog_close_button "organize-modal" %}
    """
    return format_html(
        '<button type="button" class="icon-btn icon-btn-clear size-11 justify-center"'
        ' data-modal-close="{}" aria-label="{}">{}</button>',
        dialog_id,
        _("Close"),
        render_icon("x-mark", **{"class": "w-5 h-5", "aria_hidden": "true"}),
    )
