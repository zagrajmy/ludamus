"""Text input renderer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.template.loader import render_to_string

from .errors import help_text_id

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


# The in-place look shared by text-field.html, textarea.html and select.html:
# a field dressed as the text it writes. It takes its type from the element
# around it and adds only a hover wash, a focus ring and an outline at rest,
# whose style (dashed, or dotted for a prefilled value) the template picks.
INPLACE_CLASS = (
    "[font:inherit] [color:inherit] [letter-spacing:inherit] bg-transparent"
    " border-0 rounded-md px-1.5 py-0.5 -mx-1.5 -my-0.5"
    " transition-[background-color,box-shadow] duration-150 hover:duration-0"
    " hover:bg-foreground/5 focus:outline-none focus:ring-2 focus:ring-primary/40"
    " placeholder:text-foreground-muted not-focus:outline-1"
    " not-focus:outline-warm-400 dark:not-focus:outline-neutral-600"
    " aria-invalid:outline-danger"
)


def render_input(
    field: BoundField,
    *,
    inplace: bool = False,
    fit: bool = False,
    dotted: bool = False,
    placeholder: str = "",
) -> str:
    """Render a styled ``<input>``, or with ``inplace`` one dressed as its text.

    ``fit`` sizes it to its content; ``dotted`` marks a prefilled value.

    Returns:
        HTML string of the input element.
    """
    widget = field.field.widget
    attrs = widget.attrs
    value = field.value()
    input_type = attrs.get("type", getattr(widget, "input_type", "text"))
    spellcheck = attrs.get("spellcheck")
    if spellcheck is None and input_type in _NO_SPELLCHECK_TYPES:
        spellcheck = "false"
    template = "components/text-field.html"
    if input_type == "color":
        template = "components/color-field.html"
    elif attrs.get("icon_preview"):
        template = "components/icon-field.html"
    return render_to_string(
        template,
        {
            "name": field.html_name,
            "id": field.id_for_label,
            "input_type": "text" if input_type == "color" else input_type,
            "label": field.label,
            # Stringified so falsy values render too: 0 must come out as
            # value="0", not as an empty box.
            "value": "" if value is None else str(value),
            "required": field.field.required,
            "disabled": attrs.get("disabled", False),
            "readonly": attrs.get("readonly", False),
            "placeholder": placeholder or attrs.get("placeholder", ""),
            "maxlength": attrs.get("maxlength", ""),
            # Widget attrs (e.g. Django's NumberInput derives them from
            # min_value/max_value); stringified so a 0 bound still renders.
            "min": str(attrs.get("min", "")),
            "max": str(attrs.get("max", "")),
            "inputmode": (
                attrs.get("inputmode") or _INPUTMODE_BY_TYPE.get(input_type, "")
            ),
            "pattern": attrs.get("pattern", ""),
            "autocomplete": attrs.get("autocomplete", ""),
            "datalist_id": attrs.get("list", ""),
            "spellcheck": spellcheck or "",
            "has_errors": bool(field.errors),
            "aria_describedby": help_text_id(field),
            "inplace": inplace,
            "inplace_class": INPLACE_CLASS,
            "fit": fit,
            "dotted": dotted,
        },
    )
