"""Answer shaping for imported dynamic fields: a multi-value field holds a list."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Collection


def split_imported_answers(raw: str, known: Collection[str]) -> list[str]:
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
