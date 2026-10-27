"""Select renderer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.template.loader import render_to_string

from ._choices import ChoiceGroup, grouped_choices, is_blank_choice
from .errors import help_text_id

if TYPE_CHECKING:
    from django.forms import BoundField


def _name_blank_choice(
    groups: list[ChoiceGroup], placeholder: str
) -> list[ChoiceGroup]:
    return [
        group._replace(
            options=[
                (value, placeholder if is_blank_choice(value) else label)
                for value, label in group.options
            ]
        )
        for group in groups
    ]


def render_select(
    field: BoundField, *, inplace_class: str = "", placeholder: str = ""
) -> str:
    """Render a styled ``<select>``, or with ``inplace_class`` dressed as its text.

    ``placeholder`` names the blank choice.

    Returns:
        HTML string of the select element.
    """
    groups = grouped_choices(field)
    return render_to_string(
        "components/select.html",
        {
            "name": field.html_name,
            "id": field.id_for_label,
            "groups": (
                _name_blank_choice(groups, placeholder) if placeholder else groups
            ),
            "selected": field.value(),
            "required": field.field.required,
            "disabled": field.field.disabled,
            "has_errors": bool(field.errors),
            "aria_describedby": help_text_id(field),
            "inplace_class": inplace_class,
        },
    )
