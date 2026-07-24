"""Shared machinery for the panel lists' configurable columns."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.pacts.panel import PanelColumnDTO, PanelColumnsContextDTO

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ludamus.pacts.panel import PanelFieldProtocol

FIELD_KEY_PREFIX = "field_"


def _column_order(field: PanelFieldProtocol) -> tuple[int, str]:
    return (field.order, field.name)


def all_columns(
    *, builtin_keys: Sequence[str], fields: Sequence[PanelFieldProtocol]
) -> list[PanelColumnDTO]:
    return [
        *(PanelColumnDTO(key=key) for key in builtin_keys),
        *(
            PanelColumnDTO(key=f"{FIELD_KEY_PREFIX}{field.pk}", field=field)
            for field in sorted(fields, key=_column_order)
        ),
    ]


def resolve_columns(
    *,
    keys: list[str],
    builtin_keys: Sequence[str],
    fields: Sequence[PanelFieldProtocol],
) -> list[PanelColumnDTO]:
    by_key = {
        column.key: column
        for column in all_columns(builtin_keys=builtin_keys, fields=fields)
    }
    return [column for key in keys or list(builtin_keys) if (column := by_key.get(key))]


def columns_context(
    *,
    keys: list[str],
    builtin_keys: Sequence[str],
    fields: Sequence[PanelFieldProtocol],
) -> PanelColumnsContextDTO:
    chosen = resolve_columns(keys=keys, builtin_keys=builtin_keys, fields=fields)
    chosen_keys = {column.key for column in chosen}
    return PanelColumnsContextDTO(
        chosen=chosen,
        available=[
            column
            for column in all_columns(builtin_keys=builtin_keys, fields=fields)
            if column.key not in chosen_keys
        ],
    )


def sanitize_column_keys(
    *,
    keys: list[str],
    builtin_keys: Sequence[str],
    fields: Sequence[PanelFieldProtocol],
) -> list[str]:
    valid_keys = {
        column.key for column in all_columns(builtin_keys=builtin_keys, fields=fields)
    }
    chosen: list[str] = []
    for key in keys:
        if key in valid_keys and key not in chosen:
            chosen.append(key)
    return chosen
