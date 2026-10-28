"""Textarea renderer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.template.loader import render_to_string

from .errors import help_text_id

if TYPE_CHECKING:
    from django.forms import BoundField


def render_textarea(field: BoundField, *, inplace_class: str = "") -> str:
    """Render a styled ``<textarea>``, or with ``inplace_class`` dressed as text.

    A widget with ``markdown`` set gets the Markdown editor, and one with
    ``published`` set stays readable in session recordings.

    Returns:
        HTML string of the textarea element.
    """
    widget = field.field.widget
    attrs = widget.attrs
    return render_to_string(
        "components/textarea.html",
        {
            "name": field.html_name,
            "id": field.id_for_label,
            "value": field.value() if field.value() is not None else "",
            "required": field.field.required,
            "rows": attrs.get("rows", 4),
            "placeholder": attrs.get("placeholder", ""),
            "has_errors": bool(field.errors),
            "aria_describedby": help_text_id(field),
            "inplace_class": inplace_class,
            "markdown": getattr(widget, "markdown", False),
            "unmask": getattr(widget, "published", False),
        },
    )
