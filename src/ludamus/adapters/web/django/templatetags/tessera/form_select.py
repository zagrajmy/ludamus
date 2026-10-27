"""Select renderer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.template.loader import render_to_string

from ._choices import grouped_choices
from .errors import help_text_id
from .input import INPLACE_CLASS

if TYPE_CHECKING:
    from django.forms import BoundField


def render_select(
    field: BoundField,
    *,
    inplace: bool = False,
    pill: bool = False,
    placeholder: str = "",
) -> str:
    """Render a styled ``<select>``, or with ``inplace`` one dressed as its text.

    ``pill`` dresses it as the pill the answer shows in; ``placeholder`` names
    the blank choice.

    Returns:
        HTML string of the select element.
    """
    return render_to_string(
        "components/select.html",
        {
            "name": field.html_name,
            "id": field.id_for_label,
            "groups": grouped_choices(field),
            "selected": field.value(),
            "required": field.field.required,
            "disabled": field.field.disabled,
            "has_errors": bool(field.errors),
            "aria_describedby": help_text_id(field),
            "inplace": inplace,
            "inplace_class": INPLACE_CLASS,
            "pill": pill,
            "placeholder": placeholder,
        },
    )
