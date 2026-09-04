"""Checkbox and multi-choice renderers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from django.template.loader import render_to_string
from django.utils.html import format_html

from ._choices import grouped_choices
from .errors import render_errors, render_help_text
from .label import render_label

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.forms import BoundField
    from django.forms.widgets import Widget


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
    return format_html("{}{}{}", html, render_help_text(field), render_errors(field))


class ChoiceTreeNode(Protocol):
    """A widget's nested option: its own value and label, then its children."""

    value: str
    label: str

    @property
    def children(self) -> Sequence[ChoiceTreeNode]: ...


def _selected_values(field: BoundField) -> set[str]:
    if not (value := field.value()):
        return set()
    return {str(one) for one in (value if isinstance(value, list) else [value])}


def choice_tree(widget: Widget) -> Sequence[ChoiceTreeNode]:
    """Read a widget's nested options, or nothing when it has none.

    Returns:
        The widget's `choice_tree`, empty for a widget that is a flat list.
    """
    return getattr(widget, "choice_tree", ())


def render_checkbox_tree_field(field: BoundField) -> str:
    """Render a nested checkbox tree for a widget carrying a `choice_tree`.

    Returns:
        HTML string of the labelled tree.
    """
    tree_html = render_to_string(
        "components/checkbox-tree.html",
        {
            "name": field.html_name,
            "nodes": choice_tree(field.field.widget),
            "selected": _selected_values(field),
        },
    )
    return format_html(
        "{}\n{}\n{}\n{}",
        render_label(field),
        tree_html,
        render_help_text(field),
        render_errors(field),
    )


def render_multi_choice_field(field: BoundField, *, is_radio: bool = False) -> str:
    """Render a group of radio buttons or checkboxes.

    Returns:
        HTML string of the multi-choice field.
    """
    # A checkbox or radio group has no optgroups, so a grouped field flattens
    # into one list — reading it raw would emit an input whose value is a list.
    flat = [pair for group in grouped_choices(field) for pair in group.options]
    options = []
    for i, (value, choice_label) in enumerate(flat):
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

    return format_html(
        "{}\n{}\n{}\n{}",
        render_label(field),
        group_html,
        render_help_text(field),
        render_errors(field),
    )
