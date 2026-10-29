"""File input (dropzone) renderer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.forms import ImageField
from django.template.loader import render_to_string

from ludamus.pacts.images import StoredFile

from .inplace import INPLACE_DROPZONE_LOOK

if TYPE_CHECKING:
    from django.forms import BoundField


def _initial_url_and_name(initial: object) -> tuple[str | None, str]:
    if isinstance(initial, StoredFile):
        return initial.url, initial.original_name
    return None, ""


def render_file_input(field: BoundField, *, inplace: bool = False) -> str:
    """Render a styled drag-and-drop file input.

    ``inplace`` draws it as the cover strip a session card shows: a slim row
    while empty, the card's own crop once an image is picked.

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
            "contain": getattr(field.field.widget, "fit", "cover") == "contain",
            "crop": None if inplace else getattr(field.field.widget, "crop", None),
            "multiple": getattr(field.field.widget, "allow_multiple_selected", False),
            "inplace_class": INPLACE_DROPZONE_LOOK if inplace else "",
        },
    )
