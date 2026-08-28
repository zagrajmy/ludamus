"""Reading a choice field's options, the one place that knows their shape."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from django.forms import BoundField


class ChoiceGroup(NamedTuple):
    """One optgroup, or a single ungrouped option under an empty label."""

    label: object
    options: list[tuple[object, object]]


def grouped_choices(field: BoundField) -> list[ChoiceGroup]:
    """Read a field's choices as groups.

    Django nests an optgroup by making the label a list of its own
    ``(value, label)`` pairs; an ungrouped option becomes a group of one under
    an empty label, so a caller never has to tell the two apart.

    Returns:
        The field's choices, every one of them inside a group.
    """
    groups = []
    for value, label in getattr(field.field, "choices", []):
        if isinstance(label, (list, tuple)):
            groups.append(ChoiceGroup(label=value, options=list(label)))
        else:
            groups.append(ChoiceGroup(label="", options=[(value, label)]))
    return groups


def sole_required_choice(field: BoundField) -> object | None:
    """Return the only option a required field offers, when it offers one.

    Returns:
        The value, or ``None`` when the field is optional, disabled, or leaves
        the user a choice to make.
    """
    if not field.field.required or field.field.disabled:
        return None
    real = [
        value
        for group in grouped_choices(field)
        for value, _label in group.options
        if value not in {"", None}
    ]
    return real[0] if len(real) == 1 else None
