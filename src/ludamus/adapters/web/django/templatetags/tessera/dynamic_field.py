"""The single renderer for organizer-defined personal-data and session fields.

`OrganizerFieldDTO` describes the same four shapes (text, select, multi-select,
checkbox) plus an optional free-text companion. Every page that lets someone
fill one in goes through `dynamic_field`, so a change to one shape reaches all
of them instead of drifting per template.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.template.loader import render_to_string

from ludamus.pacts import FieldAnswer

from ._registry import register

if TYPE_CHECKING:
    from ludamus.pacts import FieldValue, OrganizerFieldDTO


def _selected(value: FieldValue) -> list[str]:
    if value is None or value is False:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def field_context(
    field: OrganizerFieldDTO, *, name_prefix: str, answer: FieldAnswer
) -> dict[str, object]:
    # Everything the markup switches on, derived once. Kept separate from the
    # render so the derivation can be checked without going through a template.
    name = f"{name_prefix}_{field.slug}"
    input_id = f"id_{name}"
    selected = _selected(answer.value)
    # Order is the organizer's; label breaks ties so the list stays stable.
    options = sorted(field.options, key=lambda o: (o.order, o.label))
    help_id = f"{input_id}_help" if field.help_text else ""
    error_id = f"{input_id}_error" if answer.errors else ""
    return {
        "field": field,
        "label": field.question,
        "icon_name": field.icon,
        "name": name,
        "input_id": input_id,
        "is_required": answer.is_required,
        "errors": answer.errors,
        "choices": [("", "—"), *((o.value, o.label) for o in options)],
        "options": [
            (o.value, o.label, o.value in selected, f"{input_id}_{i}")
            for i, o in enumerate(options)
        ],
        "text_value": selected[0] if selected else "",
        "is_checked": bool(answer.value),
        "custom_name": f"{name}_custom",
        "custom_id": f"{input_id}_custom",
        "custom_value": answer.custom_value,
        "help_id": help_id,
        "error_id": error_id,
        "described_by": " ".join(part for part in (help_id, error_id) if part),
    }


@register.simple_tag
def dynamic_field(
    field: OrganizerFieldDTO, *, name_prefix: str, answer: FieldAnswer | None = None
) -> str:
    """Render one organizer-defined field, switched on its type.

    Returns:
        HTML string for the field's label, input(s), help text and errors.

    Usage:
        {% dynamic_field desc.field name_prefix=desc.name_prefix answer=desc.answer %}
    """
    return render_to_string(
        "components/dynamic-field.html",
        field_context(field, name_prefix=name_prefix, answer=answer or FieldAnswer()),
    )
