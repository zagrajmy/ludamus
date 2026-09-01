"""Select renderer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.template.loader import render_to_string

from ._choices import grouped_choices

if TYPE_CHECKING:
    from django.forms import BoundField


def render_select(field: BoundField) -> str:
    """Render a styled ``<select>``.

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
        },
    )
