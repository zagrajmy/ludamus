"""Detecting forced single-choice fields for the tessera form renderer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.utils.html import format_html

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


def forced_choice_input(field: BoundField) -> str | None:
    """Render a field whose answer is a foregone conclusion, as a hidden input.

    A required, editable field whose choices contain exactly one non-blank
    option asks nothing: there is no decision to make, so the page spends no
    pixels on it and the form submits the value on the proposer's behalf.

    Returns:
        The hidden input's HTML, or ``None`` when the field is optional,
        disabled, or offers a real choice.
    """
    if not field.field.required or field.field.disabled:
        return None
    real = [
        value
        for value, _label in _flatten_choices(getattr(field.field, "choices", []))
        if value not in {"", None}
    ]
    if len(real) != 1:
        return None
    return format_html(
        '<input type="hidden" name="{}" value="{}">', field.html_name, real[0]
    )
