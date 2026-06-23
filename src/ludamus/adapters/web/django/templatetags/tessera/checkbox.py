"""Checkbox and multi-choice renderers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.template.loader import render_to_string

from ._choices import single_required_choice
from .errors import render_errors, render_help_text
from .label import render_label

if TYPE_CHECKING:
    from django.forms import BoundField


def render_checkbox_field(field: BoundField) -> str:
    """Render a single checkbox with inline label.

    Returns:
        HTML string of the checkbox field.
    """
    html = render_to_string(
        "components/checkbox-field.html",
        {
            "name": field.html_name,
            "id": field.id_for_label,
            "label": field.label,
            "checked": bool(field.value()),
        },
    )
    return f"{html}{render_help_text(field)}{render_errors(field)}"


def render_multi_choice_field(field: BoundField, *, is_radio: bool = False) -> str:
    """Render a group of radio buttons or checkboxes.

    Returns:
        HTML string of the multi-choice field.
    """
    forced = single_required_choice(field)
    if forced is not None:
        value, label = forced
        single_html = render_to_string(
            "components/forced-choice.html",
            {
                "name": field.html_name,
                "id": field.id_for_label,
                "value": value,
                "label": label,
            },
        )
        return "\n".join(
            [
                render_label(field),
                single_html,
                render_help_text(field),
                render_errors(field),
            ]
        )

    options = []
    for i, (value, choice_label) in enumerate(field.field.choices):  # type: ignore[attr-defined]
        input_id = f"{field.id_for_label}_{i}"
        is_checked = False

        if field.value():
            if is_radio:
                is_checked = str(value) == str(field.value())
            else:
                values = (
                    field.value()
                    if isinstance(field.value(), list)
                    else [field.value()]
                )
                is_checked = str(value) in [str(v) for v in values]

        options.append((value, choice_label, is_checked, input_id))

    group_html = render_to_string(
        "components/choice-group.html",
        {
            "input_type": "radio" if is_radio else "checkbox",
            "name": field.html_name,
            "options": options,
        },
    )

    parts = [
        render_label(field),
        group_html,
        render_help_text(field),
        render_errors(field),
    ]
    return "\n".join(parts)
