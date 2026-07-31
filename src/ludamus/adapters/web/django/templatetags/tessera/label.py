"""Label renderer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.template.loader import render_to_string

if TYPE_CHECKING:
    from django.forms import BoundField


def render_label(field: BoundField, *, required: bool | None = None) -> str:
    """Render a styled ``<label>``.

    Returns:
        HTML string of the label element, or empty string if no label.
    """
    if not field.label:
        return ""

    return render_to_string(
        "components/label.html",
        {
            "for_id": field.id_for_label,
            "text": field.label,
            "required": field.field.required if required is None else required,
        },
    )
