"""Answer shaping for dynamic fields: a multi-value field holds a list."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Collection

type FieldAnswer = str | list[str] | bool


def split_answers(raw: str, known: Collection[str] = ()) -> list[str]:
    # A Forms response cell joins a checkbox question's answers with ", ", and
    # an option may contain a comma itself — a run of parts that can still grow
    # into a configured option is held back until it either matches one or
    # cannot.
    values: list[str] = []
    pending: list[str] = []
    for part in (part.strip() for part in raw.split(",")):
        pending.append(part)
        if (joined := ", ".join(pending)) in known:
            values.append(joined)
            pending.clear()
        elif not any(option.startswith(f"{joined},") for option in known):
            values.extend(value for value in pending if value)
            pending.clear()
    values.extend(value for value in pending if value)
    return [value for index, value in enumerate(values) if value not in values[:index]]


def merge_custom(
    *, chosen: FieldAnswer | None, custom: str, is_multiple: bool
) -> FieldAnswer:
    if isinstance(chosen, bool):
        return chosen
    if not is_multiple:
        return chosen or custom
    values = (
        [value for value in chosen if isinstance(value, str)]
        if isinstance(chosen, list)
        else []
    )
    for part in split_answers(custom):
        if part not in values:
            values.append(part)
    return values


def split_stored(
    *, stored: FieldAnswer | None, known: Collection[str], is_multiple: bool
) -> tuple[str | list[str], str]:
    if not isinstance(stored, str | list):
        return ([] if is_multiple else ""), ""
    values = (
        [value for value in stored if isinstance(value, str)]
        if isinstance(stored, list)
        else [stored]
    )
    chosen = [value for value in values if value in known]
    custom = ", ".join(value for value in values if value not in known)
    if is_multiple:
        return chosen, custom
    return (chosen[0] if chosen else ""), custom
