"""Textarea renderer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.template.loader import render_to_string

from ludamus.gates.web.django.forms import MarkdownTextarea

from .errors import help_text_id

if TYPE_CHECKING:
    from django.forms import BoundField


def render_textarea(field: BoundField, *, inplace_class: str = "") -> str:
    """Render a styled ``<textarea>``, or with ``inplace_class`` dressed as text.

    A ``MarkdownTextarea`` gets the Markdown editor, and a published one
    stays readable in session recordings.

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
            "markdown": isinstance(widget, MarkdownTextarea),
            "unmask": isinstance(widget, MarkdownTextarea) and widget.published,
        },
    )
