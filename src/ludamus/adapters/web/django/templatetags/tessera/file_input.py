"""File input (dropzone) renderer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.forms import ImageField
from django.template.loader import render_to_string

from ludamus.pacts.images import StoredFile

if TYPE_CHECKING:
    from django.forms import BoundField


def _initial_url_and_name(initial: object) -> tuple[str | None, str]:
    if isinstance(initial, StoredFile):
        return initial.url, initial.original_name
    return None, ""


def render_file_input(field: BoundField) -> str:
    """Render a styled drag-and-drop file input.

    Returns:
        HTML string of the dropzone element.
    """
    attrs = field.field.widget.attrs
    is_image = isinstance(field.field, ImageField)
    accept = attrs.get("accept") or ("image/*" if is_image else "")
    initial_url, initial_name = _initial_url_and_name(field.value())
    if accept and not is_image:
        is_image = all(t.strip().startswith("image/") for t in accept.split(","))
    dropzone_state = ("image" if is_image else "file") if initial_url else "empty"
    return render_to_string(
        "components/file-dropzone.html",
        {
            "name": field.html_name,
            "id": field.id_for_label,
            "label": field.label,
            "required": field.field.required,
            "accept": accept,
            "has_errors": bool(field.errors),
            "errors": field.errors,
            "initial_url": initial_url,
            "initial_name": initial_name,
            "dropzone_state": dropzone_state,
            "contain": attrs.get("data-fit") == "contain",
        },
    )
