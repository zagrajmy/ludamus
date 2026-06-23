"""Detecting forced single-choice fields for the tessera form renderer."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from django.forms import BoundField


def _flatten_choices(
    choices: Iterable[tuple[object, object]],
) -> Iterator[tuple[object, object]]:
    for value, label in choices:
        if isinstance(label, (list, tuple)):
            yield from label  # optgroup: label is itself a list of (value, label)
        else:
            yield value, label


def single_required_choice(field: BoundField) -> tuple[object, str] | None:
    """Return the only selectable choice when picking is a foregone conclusion.

    A required, editable field whose choices contain exactly one non-blank
    option forces the user to "choose" the only thing available. The caller can
    render the value as static text plus a hidden input instead of a dropdown or
    radio group the user would have to operate.

    Returns:
        ``(value, label)`` for the sole option, or ``None`` when the field is
        optional, disabled, or offers a real choice.
    """
    if not field.field.required or field.field.disabled:
        return None
    real = [
        (value, label)
        for value, label in _flatten_choices(getattr(field.field, "choices", []))
        if value not in {"", None}
    ]
    if len(real) != 1:
        return None
    value, label = real[0]
    return value, str(label)
