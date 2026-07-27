"""Answer shaping for dynamic fields: a multi-value field holds a list."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Collection

type FieldAnswer = str | list[str] | bool


def split_custom(raw: str) -> list[str]:
    values: list[str] = []
    for part in (part.strip() for part in raw.split(",")):
        if part and part not in values:
            values.append(part)
    return values


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
    for part in split_custom(custom):
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
