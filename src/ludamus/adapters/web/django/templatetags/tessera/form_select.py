"""Select renderer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.template.loader import render_to_string

from ._choices import single_required_choice

if TYPE_CHECKING:
    from django.forms import BoundField


def render_select(field: BoundField) -> str:
    """Render a styled ``<select>``.

    Returns:
        HTML string of the select element.
    """
    forced = single_required_choice(field)
    if forced is not None:
        value, label = forced
        return render_to_string(
            "components/forced-choice.html",
            {
                "name": field.html_name,
                "id": field.id_for_label,
                "value": value,
                "label": label,
            },
        )
    return render_to_string(
        "components/select.html",
        {
            "name": field.html_name,
            "id": field.id_for_label,
            "groups": _grouped_choices(field),
            "selected": field.value(),
            "required": field.field.required,
            "disabled": field.field.disabled,
            "has_errors": bool(field.errors),
        },
    )


def _grouped_choices(field: BoundField) -> list[dict[str, object]]:
    groups: list[dict[str, object]] = []
    for value, label in getattr(field.field, "choices", []):
        if isinstance(label, (list, tuple)):
            groups.append({"label": value, "options": list(label)})
        else:
            groups.append({"label": "", "options": [(value, label)]})
    return groups
