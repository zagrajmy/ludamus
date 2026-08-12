"""What a panel list column is called, and how its cell renders.

The mill owns which built-in keys exist; this owns what each one means to a
reader. Both lists build their header labels, their chooser rows and their
cells from the same table, so a column can't be named in one place and
rendered in another.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.generic.base import View

from ludamus.gates.web.django.chronology.panel.views.base import (
    EventContextMixin,
    PanelAccessMixin,
    PanelRequest,
    facilitator_tab_urls,
    format_field_value,
    proposal_tab_urls,
)
from ludamus.gates.web.django.forms import ACCREDITATION_TYPE_LABELS
from ludamus.mills.panel_columns import FACILITATOR_BUILTIN_KEYS, PROPOSAL_BUILTIN_KEYS
from ludamus.pacts.panel import EmptyColumnSelectionError
from ludamus.pacts.submissions import AccreditationType

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from django.http import HttpResponse
    from django.utils.functional import _StrPromise

    from ludamus.gates.web.django.panel import PanelNav
    from ludamus.pacts import FacilitatorListItemDTO, SessionListItemDTO
    from ludamus.pacts.panel import (
        FacilitatorPanelServiceProtocol,
        PanelColumnDTO,
        PanelColumnServiceProtocol,
    )

TEXT_KIND = "text"


class PanelRowProtocol(Protocol):
    """A row of either list."""

    pk: int


class ColumnMetaProtocol(Protocol):
    """What naming a column needs — no row type involved."""

    @property
    def label(self) -> _StrPromise: ...
    @property
    def kind(self) -> str: ...


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
        "organizer": BuiltinColumn(
            label=gettext_lazy("Organizer"), cell=lambda f: f.organizer_name or "—"
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


def column_views(
    columns: Sequence[PanelColumnDTO], builtins: Mapping[str, ColumnMetaProtocol]
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


def facilitator_column_values(
    *,
    panel: FacilitatorPanelServiceProtocol,
    facilitators: Sequence[FacilitatorListItemDTO],
    columns: Sequence[PanelColumnDTO],
) -> dict[int, dict[str, str]]:
    # Lives here rather than on either page because the facilitator list and
    # the timetable's facilitator picker both render these cells.
    return column_values(
        rows=facilitators,
        columns=columns,
        builtins=FACILITATOR_COLUMNS,
        raw_values=panel.column_values(
            facilitator_ids=[f.pk for f in facilitators],
            field_ids=[c.field.pk for c in columns if c.field is not None],
        ),
    )


@dataclass(frozen=True)
class PanelColumnSet:
    """Everything one list's columns chooser differs by."""

    builtins: Mapping[str, ColumnMetaProtocol]
    active_nav: PanelNav
    tab_urls: Callable[[str], dict[str, str]]
    template: str
    list_route: str
    service: Callable[[PanelRequest], PanelColumnServiceProtocol]


class PanelColumnsPageView(PanelAccessMixin, EventContextMixin, View):
    """Choose which columns a panel list shows, for either list."""

    request: PanelRequest
    column_set: PanelColumnSet

    def _render(
        self, *, context: dict[str, Any], slug: str, event_pk: int, error: str | None
    ) -> HttpResponse:
        columns = self.column_set.service(self.request).columns_context(event_pk)
        context["active_nav"] = self.column_set.active_nav
        context["active_tab"] = "columns"
        context["tab_urls"] = self.column_set.tab_urls(slug)
        context["chosen_columns"] = column_views(
            columns.chosen, self.column_set.builtins
        )
        context["available_columns"] = column_views(
            columns.available, self.column_set.builtins
        )
        context["error"] = error
        return TemplateResponse(self.request, self.column_set.template, context)

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        return self._render(
            context=context, slug=slug, event_pk=current_event.pk, error=None
        )

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        # The chosen keys arrive in display order; the service drops anything
        # that isn't this event's own column.
        try:
            self.column_set.service(self.request).set_columns(
                event_id=current_event.pk, columns=self.request.POST.getlist("columns")
            )
        except EmptyColumnSelectionError:
            return self._render(
                context=context,
                slug=slug,
                event_pk=current_event.pk,
                error=_("Pick at least one column to show."),
            )

        messages.success(self.request, _("Columns updated."))
        return redirect(self.column_set.list_route, slug=slug)


class FacilitatorColumnsPageView(PanelColumnsPageView):
    """Choose which personal-data fields show as columns on the list."""

    column_set = PanelColumnSet(
        builtins=FACILITATOR_COLUMNS,
        active_nav="facilitators",
        tab_urls=facilitator_tab_urls,
        template="panel/facilitator-columns.html",
        list_route="panel:facilitators",
        service=lambda request: request.services.facilitator_panel,
    )


class ProposalColumnsPageView(PanelColumnsPageView):
    """Choose which session fields show as columns on the proposals list."""

    column_set = PanelColumnSet(
        builtins=PROPOSAL_COLUMNS,
        active_nav="proposals",
        tab_urls=proposal_tab_urls,
        template="panel/proposal-columns.html",
        list_route="panel:proposals",
        service=lambda request: request.services.proposal_panel,
    )
