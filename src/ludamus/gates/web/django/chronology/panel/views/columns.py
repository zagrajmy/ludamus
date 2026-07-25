"""What a panel list column is called, and how its cell renders.

The mill owns which built-in keys exist; this owns what each one means to a
reader. Both lists build their header labels, their chooser rows and their
cells from the same table, so a column can't be named in one place and
rendered in another.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from ludamus.gates.web.django.chronology.panel.views.base import format_field_value
from ludamus.gates.web.django.forms import ACCREDITATION_TYPE_LABELS
from ludamus.mills.panel_columns import FACILITATOR_BUILTIN_KEYS, PROPOSAL_BUILTIN_KEYS
from ludamus.pacts.submissions import AccreditationType

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from django.utils.functional import _StrPromise

    from ludamus.pacts import FacilitatorListItemDTO, SessionListItemDTO
    from ludamus.pacts.panel import PanelColumnDTO

TEXT_KIND = "text"


class PanelRowProtocol(Protocol):
    """A row of either list."""

    pk: int


@dataclass(frozen=True)
class BuiltinColumn[RowT: PanelRowProtocol]:
    """A built-in column: its header, and the cell it puts in each row.

    `cell` is None for a column the template renders itself — a status badge
    and a localized date aren't strings — and `kind` tells it which.
    """

    label: _StrPromise
    cell: Callable[[RowT], str] | None = None
    kind: str = TEXT_KIND


@dataclass(frozen=True)
class PanelColumnView:
    """One column as a template reads it."""

    key: str
    label: str
    kind: str


def builtin_columns[RowT: PanelRowProtocol](
    keys: Sequence[str], columns: Mapping[str, BuiltinColumn[RowT]]
) -> dict[str, BuiltinColumn[RowT]]:
    # The mill's key list is the source of truth. A key with nothing here — or
    # something here the mill never offers — fails at import instead of
    # rendering as a blank cell nobody can explain.
    if set(keys) != set(columns):
        message = f"built-in columns don't match {sorted(keys)}"
        raise ValueError(message)
    return {key: columns[key] for key in keys}


FACILITATOR_COLUMNS: dict[str, BuiltinColumn[FacilitatorListItemDTO]] = builtin_columns(
    FACILITATOR_BUILTIN_KEYS,
    {
        "name": BuiltinColumn(
            label=gettext_lazy("Display Name"), cell=lambda f: f.display_name
        ),
        "linked": BuiltinColumn(
            label=gettext_lazy("Linked User"),
            cell=lambda f: _("Linked") if f.user_id else _("None"),
        ),
        "sessions": BuiltinColumn(
            label=gettext_lazy("Sessions"), cell=lambda f: str(f.session_count)
        ),
        "accreditation": BuiltinColumn(
            label=gettext_lazy("Accreditation"),
            cell=lambda f: str(
                ACCREDITATION_TYPE_LABELS[AccreditationType(f.accreditation_type)]
            ),
        ),
    },
)

PROPOSAL_COLUMNS: dict[str, BuiltinColumn[SessionListItemDTO]] = builtin_columns(
    PROPOSAL_BUILTIN_KEYS,
    {
        "title": BuiltinColumn(label=gettext_lazy("Title"), cell=lambda p: p.title),
        "host": BuiltinColumn(
            label=gettext_lazy("Display Name"), cell=lambda p: p.display_name
        ),
        "category": BuiltinColumn(
            label=gettext_lazy("Category"), cell=lambda p: p.category_name
        ),
        "status": BuiltinColumn(label=gettext_lazy("Status"), kind="status"),
        "created": BuiltinColumn(label=gettext_lazy("Created"), kind="created"),
    },
)


def column_views[RowT: PanelRowProtocol](
    columns: Sequence[PanelColumnDTO], builtins: Mapping[str, BuiltinColumn[RowT]]
) -> list[PanelColumnView]:
    return [
        PanelColumnView(
            key=column.key,
            label=(
                column.field.name
                if column.field is not None
                else str(builtins[column.key].label)
            ),
            kind=(TEXT_KIND if column.field is not None else builtins[column.key].kind),
        )
        for column in columns
    ]


def column_values[RowT: PanelRowProtocol](
    *,
    rows: Sequence[RowT],
    columns: Sequence[PanelColumnDTO],
    builtins: Mapping[str, BuiltinColumn[RowT]],
    raw_values: Mapping[int, Mapping[str, str | list[str] | bool]],
) -> dict[int, dict[str, str]]:
    # One ready-to-render string per (row, column), so the template renders
    # every column the same way whatever the organizer chose. Columns the
    # template renders itself contribute nothing here.
    values: dict[int, dict[str, str]] = {}
    for row in rows:
        cells: dict[str, str] = {}
        for column in columns:
            if (field := column.field) is not None:
                cells[column.key] = format_field_value(
                    value=raw_values.get(row.pk, {}).get(field.slug)
                )
            elif (cell := builtins[column.key].cell) is not None:
                cells[column.key] = cell(row)
        values[row.pk] = cells
    return values
