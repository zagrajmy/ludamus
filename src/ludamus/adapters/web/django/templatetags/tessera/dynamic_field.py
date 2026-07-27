"""The single renderer for organizer-defined personal-data and session fields.

Both field DTOs describe the same four shapes (text, select, multi-select,
checkbox) plus an optional free-text companion. Every page that lets someone
fill one in goes through `dynamic_field`, so a change to one shape reaches all
of them instead of drifting per template.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import TYPE_CHECKING, TypedDict

from django.template.loader import render_to_string
from django.utils.safestring import mark_safe

from ._registry import register

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ludamus.pacts import (
        PersonalDataFieldDTO,
        PersonalDataFieldOptionDTO,
        SessionFieldDTO,
        SessionFieldOptionDTO,
    )

    _FieldDTO = PersonalDataFieldDTO | SessionFieldDTO
    _Option = PersonalDataFieldOptionDTO | SessionFieldOptionDTO

_Value = str | list[str] | bool | None


@dataclass(frozen=True, slots=True)
class FieldAnswer:
    """What someone has filled in for one field, plus how it must be validated.

    Pages backed by a Django form build this from the bound field; pages that
    only have a stored value pass that value straight to the tag instead.
    """

    value: _Value = None
    custom_value: str = ""
    errors: list[str] = dataclass_field(default_factory=list)
    is_required: bool = False


class FieldDescriptor(TypedDict):
    """One field ready to render: what to ask, where to post it, what's filled in.

    Form-backed pages build a list of these and hand each straight to the tag.
    """

    field: _FieldDTO
    name_prefix: str
    answer: FieldAnswer


def _selected(value: _Value) -> list[str]:
    if value is None or value is False:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


@register.simple_tag
def dynamic_field(
    field: _FieldDTO, *, name_prefix: str, answer: FieldAnswer | _Value = None
) -> str:
    """Render one organizer-defined field, switched on its type.

    Returns:
        HTML string for the field's label, input(s), help text and errors.

    Usage:
        {% dynamic_field field name_prefix="session_field" answer=current %}
        {% dynamic_field desc.field name_prefix=desc.name_prefix answer=desc.answer %}
    """
    if not isinstance(answer, FieldAnswer):
        answer = FieldAnswer(value=answer)
    name = f"{name_prefix}_{field.slug}"
    input_id = f"id_{name}"
    selected = _selected(answer.value)
    # Order is the organizer's; label breaks ties so the list stays stable.
    # Both field types carry the same option shape, so one sort serves both.
    unsorted: Sequence[_Option] = field.options
    options = sorted(unsorted, key=lambda o: (o.order, o.label))
    return mark_safe(  # ruff:ignore[suspicious-mark-safe-usage]
        render_to_string(
            "components/dynamic-field.html",
            {
                "field": field,
                "label": field.question,
                # Only session fields carry an icon; personal-data fields don't.
                "icon_name": getattr(field, "icon", ""),
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
            },
        )
    )
