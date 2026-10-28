"""Textarea renderer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.template.loader import render_to_string

from .errors import help_text_id

if TYPE_CHECKING:
    from django.forms import BoundField


def render_textarea(field: BoundField, *, inplace_class: str = "") -> str:
    """Render a styled ``<textarea>``, or with ``inplace_class`` dressed as text.

    A form marks a field whose text is read as Markdown with the widget attr
    ``data-markdown-editor``, and the textarea gets the Markdown editor. One
    whose text is published, never personal, sets ``data-ph-unmask`` and
    stays readable in session recordings.

    Returns:
        HTML string of the textarea element.
    """
    attrs = field.field.widget.attrs
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
            "markdown": bool(attrs.get("data-markdown-editor")),
            "unmask": bool(attrs.get("data-ph-unmask")),
        },
    )
