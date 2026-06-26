"""Text input renderer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.template.loader import render_to_string

if TYPE_CHECKING:
    from django.forms import BoundField

# Sensible mobile-keyboard defaults by input type (overridable per widget).
_INPUTMODE_BY_TYPE = {
    "email": "email",
    "tel": "tel",
    "url": "url",
    "number": "numeric",
    "search": "search",
}
# Spellcheck/autocorrect is wrong for these (addresses, codes, secrets).
_NO_SPELLCHECK_TYPES = frozenset({"email", "url", "tel", "password"})


def render_input(field: BoundField) -> str:
    """Render a styled ``<input>``.

    Returns:
        HTML string of the input element.
    """
    widget = field.field.widget
    attrs = widget.attrs
    value = field.value()
    input_type = getattr(widget, "input_type", "text")
    spellcheck = attrs.get("spellcheck")
    if spellcheck is None and input_type in _NO_SPELLCHECK_TYPES:
        spellcheck = "false"
    return render_to_string(
        "components/text-field.html",
        {
            "name": field.html_name,
            "id": field.id_for_label,
            "input_type": input_type,
            "value": value if value is not None else "",
            "required": field.field.required,
            "disabled": attrs.get("disabled", False),
            "readonly": attrs.get("readonly", False),
            "placeholder": attrs.get("placeholder", ""),
            "maxlength": attrs.get("maxlength", ""),
            "inputmode": attrs.get("inputmode")
            or _INPUTMODE_BY_TYPE.get(input_type, ""),
            "pattern": attrs.get("pattern", ""),
            "autocomplete": attrs.get("autocomplete", ""),
            "spellcheck": spellcheck or "",
            "has_errors": bool(field.errors),
        },
    )
