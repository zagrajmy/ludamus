"""Reading a bound field's options: where the renderer knows their shape."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from django.forms import BoundField
    from django.utils.functional import Promise


class ChoiceGroup(NamedTuple):
    """One optgroup, or a single ungrouped option under an empty label."""

    label: str | Promise
    options: list[tuple[object, str | Promise]]


class SoleChoice(NamedTuple):
    """The one option a field offers: what it submits, and what it is called."""

    value: object
    label: str | Promise


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
            # Caught once for every field this renderer draws, rather than
            # in each builder that might leave a group unfilled.
            if options := list(label):
                groups.append(ChoiceGroup(label=value, options=options))
        else:
            groups.append(ChoiceGroup(label="", options=[(value, label)]))
    return groups


def sole_required_choice(field: BoundField) -> SoleChoice | None:
    """Return the option a field carries instead of asking for it.

    The single answer to "has this field stopped asking?", so the renderer
    that drops the control and the page that names the value in its place
    cannot disagree — a rejected field renders in full, and prose calling it
    settled would contradict the error beside it.

    Returns:
        The value and its label, or ``None`` when the field is optional,
        disabled, rejected, or leaves the user a choice to make.
    """
    if not field.field.required or field.field.disabled or field.errors:
        return None
    real = [
        (value, label)
        for group in grouped_choices(field)
        for value, label in group.options
        if value not in {"", None}
    ]
    return SoleChoice(*real[0]) if len(real) == 1 else None
