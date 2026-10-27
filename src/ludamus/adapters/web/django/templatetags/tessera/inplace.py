"""In-place fields: a form field dressed as the text it writes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.forms.widgets import FileInput, NumberInput, Select, Textarea
from django.template.loader import render_to_string
from django.utils.html import format_html, format_html_join

from ._choices import sole_required_choice
from ._registry import register
from .file_input import render_file_input

if TYPE_CHECKING:
    from django.forms import BoundField


def _kind(field: BoundField) -> str:
    widget = field.field.widget
    if isinstance(widget, Textarea):
        return "textarea"
    if isinstance(widget, Select):
        return "select"
    if isinstance(widget, NumberInput):
        return "number"
    return "text"


@register.simple_tag
def tessera_inplace(
    field: BoundField,
    *,
    placeholder: str = "",
    select_look: str = "text",
    fit: bool = False,
    outlined: bool = False,
) -> str:
    """Render a bound field in the look of the text it writes, plus its errors.

    Returns:
        HTML string of the control followed by its error messages.

    Usage:
        {% tessera_inplace form.title placeholder=_("Session title") %}
        {% tessera_inplace form.facilitator_name fit=True outlined=True %}
    """
    if isinstance(field.field.widget, FileInput):
        return render_file_input(field, strip=True)
    if isinstance(field.field.widget, Select) and (sole := sole_required_choice(field)):
        return format_html(
            '<input type="hidden" name="{}" value="{}">', field.html_name, sole.value
        )
    attrs = field.field.widget.attrs
    value = field.value()
    error_id = f"{field.auto_id}_error" if field.errors else ""
    control = render_to_string(
        "components/inplace-field.html",
        {
            "kind": _kind(field),
            "name": field.html_name,
            "id": field.auto_id,
            "value": "" if value is None else str(value),
            "placeholder": placeholder or attrs.get("placeholder", ""),
            "required": field.field.required,
            "has_errors": bool(field.errors),
            "aria_describedby": error_id,
            "maxlength": attrs.get("maxlength", ""),
            "min": str(attrs.get("min", "")),
            "max": str(attrs.get("max", "")),
            "choices": getattr(field.field, "choices", []),
            "select_look": select_look,
            "fit": fit,
            "outlined": outlined,
        },
    )
    if not field.errors:
        return control
    return control + format_html(
        '<div id="{}" class="mt-1">{}</div>',
        error_id,
        format_html_join(
            "", '<p class="text-sm text-danger">{}</p>', ((e,) for e in field.errors)
        ),
    )
