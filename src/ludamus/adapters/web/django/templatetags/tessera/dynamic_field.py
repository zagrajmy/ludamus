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
from .inplace import inplace_look

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django.utils.functional import Promise

    from ludamus.pacts import FieldValue, OrganizerFieldDTO


def _selected(value: FieldValue) -> list[str]:
    if value is None or value is False:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def _name_blank_choice[V](
    choices: Iterable[tuple[V, str | Promise]], name: str | Promise
) -> list[tuple[V, str | Promise]]:
    """Relabel the blank choice, so an empty select asks its question.

    Returns:
        The choices with the blank one, "" or None, labelled ``name``.
    """
    return [(value, name if value in {"", None} else label) for value, label in choices]


def field_context(
    field: OrganizerFieldDTO,
    *,
    name_prefix: str,
    answer: FieldAnswer,
    inplace: bool = False,
    visibility_badge: bool = True,
) -> dict[str, object]:
    # Everything the markup switches on, derived once. Kept separate from the
    # render so the derivation can be checked without going through a template.
    name = f"{name_prefix}_{field.slug}"
    input_id = f"id_{name}"
    custom_id = f"{input_id}_custom"
    selected = _selected(answer.value)
    options = field.sorted_options
    help_id = f"{input_id}_help" if field.help_text else ""
    error_id = f"{input_id}_error" if answer.errors else ""
    custom_error_id = f"{custom_id}_error" if answer.custom_errors else ""
    return {
        "field": field,
        "label": field.question,
        # A checkbox's question is what it says yes to, so it stays the label.
        "heading": (
            field.name if inplace and field.field_type != "checkbox" else field.question
        ),
        "placeholder": field.question if inplace else "",
        "inplace": inplace,
        # Where the box a field sits in already says who sees it, it says it
        # once: in place, or inside the organizers-only box.
        "visibility_badge": visibility_badge and not inplace,
        "label_class": (
            "text-sm font-semibold text-foreground-secondary"
            if inplace
            else "block text-sm font-medium text-foreground-secondary"
            " first-letter:uppercase"
        ),
        "text_class": inplace_look(shape="text") if inplace else "",
        "pill_class": inplace_look(shape="pill") if inplace else "",
        "icon_name": field.icon,
        "name": name,
        "input_id": input_id,
        "is_required": answer.is_required,
        "control_required": field.control_required(is_required=answer.is_required),
        "offers_custom": field.offers_custom_input,
        "errors": answer.errors,
        "choices": (
            _name_blank_choice(field.choices, field.question)
            if inplace
            else field.choices
        ),
        "options": [
            (o.value, o.label, o.value in selected, f"{input_id}_{i}")
            for i, o in enumerate(options)
        ],
        "text_value": selected[0] if selected else "",
        "is_checked": bool(answer.value),
        "custom_name": f"{name}_custom",
        "custom_id": custom_id,
        "custom_value": answer.custom_value,
        "custom_errors": answer.custom_errors,
        "custom_error_id": custom_error_id,
        # The write-in's help lives on the control it stands in for, so the
        # companion points at the same help text and at its own errors.
        "custom_described_by": " ".join(
            part for part in (help_id, custom_error_id) if part
        ),
        "help_id": help_id,
        "error_id": error_id,
        "described_by": " ".join(part for part in (help_id, error_id) if part),
    }


@register.simple_tag
def dynamic_field(
    field: OrganizerFieldDTO,
    *,
    name_prefix: str,
    answer: FieldAnswer | None = None,
    inplace: bool = False,
    visibility_badge: bool = True,
) -> str:
    """Render one organizer-defined field, switched on its type.

    ``inplace`` writes it the way the session modal reads the answer;
    ``visibility_badge=False`` drops the eye/lock where the surrounding box
    already says who sees the field.

    Returns:
        HTML string for the field's label, input(s), help text and errors.

    Usage:
        {% dynamic_field desc.field name_prefix=desc.name_prefix answer=desc.answer %}
    """
    return render_to_string(
        "components/dynamic-field.html",
        field_context(
            field,
            name_prefix=name_prefix,
            answer=answer or FieldAnswer(),
            inplace=inplace,
            visibility_badge=visibility_badge,
        ),
    )
