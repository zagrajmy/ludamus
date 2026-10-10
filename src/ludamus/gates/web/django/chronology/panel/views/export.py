"""One spreadsheet download per organizer list: every row the filters match.

The row-and-cell machinery is the lists' own (`columns.py`); this only swaps
the destination from a table on screen to an `.ods` file, and holds what each
list's export differs by.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from django.http import HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.generic.base import View

from ludamus.gates.web.django.chronology.panel.views.base import (
    EventContextMixin,
    PanelAccessMixin,
    PanelRequest,
    format_field_value,
    track_filter_context,
)
from ludamus.gates.web.django.chronology.panel.views.columns import (
    FACILITATOR_COLUMN_SET,
    FACILITATOR_COLUMNS,
    PROPOSAL_COLUMN_SET,
    PROPOSAL_COLUMNS,
    BuiltinColumn,
    PanelColumnSet,
    PanelRowProtocol,
    column_values,
    column_views,
)
from ludamus.gates.web.django.chronology.panel.views.discounts import (
    read_discount_query,
)
from ludamus.gates.web.django.chronology.panel.views.facilitators import (
    read_facilitator_query,
)
from ludamus.gates.web.django.chronology.panel.views.proposals import (
    PROPOSAL_STATUS_LABELS,
    read_proposal_query,
)
from ludamus.gates.web.django.forms import DISCOUNT_KIND_LABELS
from ludamus.gates.web.django.sphere.marks import attach_facilitator_guild_marks
from ludamus.links.ods import spreadsheet_bytes
from ludamus.pacts import FacilitatorListItemDTO, SessionListItemDTO
from ludamus.pacts.durations import MINUTES_PER_HOUR
from ludamus.pacts.panel import (
    FacilitatorListQuery,
    PanelColumnDTO,
    PanelColumnsContextDTO,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from django.utils.functional import _StrPromise


ODS_CONTENT_TYPE = "application/vnd.oasis.opendocument.spreadsheet"
# One chooser page for every list; what it says comes from the export set.
LIST_EXPORT_TEMPLATE = "panel/list-export.html"


@dataclass(frozen=True)
class ExportRows[RowT: PanelRowProtocol]:
    """The full filtered result and the values its cells read from."""

    rows: Sequence[RowT]
    raw_values: Mapping[int, Mapping[str, str | list[str] | bool]]
    # Values a row cannot supply itself, keyed by row pk then column key.
    computed: Mapping[int, Mapping[str, str]] = field(default_factory=dict)


class ExportRowsProtocol[RowT: PanelRowProtocol](Protocol):
    def __call__(
        self, *, request: PanelRequest, event_pk: int, columns: Sequence[PanelColumnDTO]
    ) -> ExportRows[RowT]: ...


@dataclass(frozen=True)
class ExportChooser:
    """What one list's column chooser says; the page itself is shared."""

    tabs_partial: str
    page_title: _StrPromise
    help_text: _StrPromise


@dataclass(frozen=True)
class PanelExportSet[RowT: PanelRowProtocol]:
    """Everything one list's export differs by."""

    columns: PanelColumnSet[RowT]
    # Overrides `columns.builtins` per key: a column the list renders itself
    # (a badge, a date) still needs a string in a file. A key the list has no
    # column for is export-only, and offered by the chooser beside the rest.
    export_cells: Mapping[str, BuiltinColumn[RowT]]
    rows: ExportRowsProtocol[RowT]
    sheet_title: _StrPromise
    filename_part: str
    # The chooser page; without one a GET downloads `default_keys` at once.
    chooser: ExportChooser | None = None
    default_keys: Sequence[str] | None = None

    @property
    def cells(self) -> dict[str, BuiltinColumn[RowT]]:
        return {**self.columns.builtins, **self.export_cells}


def offered_columns[RowT: PanelRowProtocol](
    *, request: PanelRequest, event_pk: int, export_set: PanelExportSet[RowT]
) -> PanelColumnsContextDTO:
    # The list's own columns, then the export-only ones — each key once.
    context = export_set.columns.service(request).columns_context(event_pk)
    known = {column.key for column in (*context.chosen, *context.available)}
    extra = [
        PanelColumnDTO(key=key) for key in export_set.export_cells if key not in known
    ]
    return PanelColumnsContextDTO(
        chosen=context.chosen, available=[*context.available, *extra]
    )


def export_columns[RowT: PanelRowProtocol](
    *,
    request: PanelRequest,
    event_pk: int,
    export_set: PanelExportSet[RowT],
    keys: Sequence[str] | None,
) -> list[PanelColumnDTO]:
    # The one place a key becomes a column. A key that is not this event's own
    # is dropped, never looked up: a `field_<pk>` that did not come back from
    # this event's columns context would otherwise read another event's data.
    offered = offered_columns(request=request, event_pk=event_pk, export_set=export_set)
    if keys is None:
        return list(offered.chosen)
    by_key = {column.key: column for column in (*offered.chosen, *offered.available)}
    return [by_key[key] for key in dict.fromkeys(keys) if key in by_key]


class PanelExportPageView[RowT: PanelRowProtocol](
    PanelAccessMixin, EventContextMixin, View
):
    """Choose columns and download a panel list as a spreadsheet, for any list."""

    request: PanelRequest
    export_set: PanelExportSet[RowT]

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        # A `columns` param, even an empty one, is the chooser's submit.
        submitted = "columns" in self.request.GET
        chooser = self.export_set.chooser
        if chooser is not None and not submitted:
            return self._render(
                chooser=chooser,
                context=context,
                slug=slug,
                event_pk=current_event.pk,
                error=None,
            )
        columns = export_columns(
            request=self.request,
            event_pk=current_event.pk,
            export_set=self.export_set,
            keys=(
                self.request.GET.getlist("columns")
                if submitted
                else self.export_set.default_keys
            ),
        )
        if not columns:
            if chooser is not None:
                return self._render(
                    chooser=chooser,
                    context=context,
                    slug=slug,
                    event_pk=current_event.pk,
                    error=_("Pick at least one column to export."),
                )
            # No chooser, so nowhere to show the error: a `columns` param that
            # resolves to nothing falls back to the fixed sheet rather than
            # writing a file of empty rows.
            columns = export_columns(
                request=self.request,
                event_pk=current_event.pk,
                export_set=self.export_set,
                keys=self.export_set.default_keys,
            )
        return self._download(slug=slug, event_pk=current_event.pk, columns=columns)

    def _render(
        self,
        *,
        chooser: ExportChooser,
        context: dict[str, object],
        slug: str,
        event_pk: int,
        error: str | None,
    ) -> HttpResponse:
        offered = offered_columns(
            request=self.request, event_pk=event_pk, export_set=self.export_set
        )
        context["active_nav"] = self.export_set.columns.active_nav
        context["active_tab"] = "export"
        context["tab_urls"] = self.export_set.columns.tab_urls(slug)
        context["tabs_partial"] = chooser.tabs_partial
        context["page_title"] = chooser.page_title
        context["help_text"] = chooser.help_text
        # The sheet's name is the list's name, on screen as in the file.
        context["list_name"] = self.export_set.sheet_title
        context["chosen_columns"] = column_views(offered.chosen, self.export_set.cells)
        context["available_columns"] = column_views(
            offered.available, self.export_set.cells
        )
        # The filters the organizer arrived with ride along as hidden inputs,
        # so the download they submit reads the same ones.
        context["hidden_params"] = [
            (name, value)
            for name in self.request.GET
            if name != "columns"
            for value in self.request.GET.getlist(name)
        ]
        context["error"] = error
        return TemplateResponse(self.request, LIST_EXPORT_TEMPLATE, context)

    def _download(
        self, *, slug: str, event_pk: int, columns: Sequence[PanelColumnDTO]
    ) -> HttpResponse:
        loaded = self.export_set.rows(
            request=self.request, event_pk=event_pk, columns=columns
        )
        cells = column_values(
            rows=loaded.rows,
            columns=columns,
            builtins=self.export_set.cells,
            raw_values=loaded.raw_values,
        )
        headers = [view.label for view in column_views(columns, self.export_set.cells)]
        body = [
            [values.get(column.key, "") for column in columns]
            # One merged dict per row, not per cell; a computed value wins over
            # the row's own cell for the same key.
            for values in (
                {**cells.get(row.pk, {}), **loaded.computed.get(row.pk, {})}
                for row in loaded.rows
            )
        ]
        content = spreadsheet_bytes(
            rows=[headers, *body], sheet_title=str(self.export_set.sheet_title)
        )
        response = HttpResponse(content, content_type=ODS_CONTENT_TYPE)
        filename = f"{slug}-{self.export_set.filename_part}-{timezone.localdate()}.ods"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


def _proposal_rows(
    *, request: PanelRequest, event_pk: int, columns: Sequence[PanelColumnDTO]
) -> ExportRows[SessionListItemDTO]:
    _tracks, _managed, track_pk = track_filter_context(request, event_pk)
    query = read_proposal_query(request, track_pk=track_pk)
    panel = request.services.proposal_panel
    proposals = panel.list_context(event_id=event_pk, query=query).proposals
    return ExportRows(
        rows=proposals,
        raw_values=panel.column_values(
            session_ids=[p.pk for p in proposals],
            field_ids=[c.field.pk for c in columns if c.field is not None],
        ),
    )


PROPOSAL_EXPORT_CELLS: dict[str, BuiltinColumn[SessionListItemDTO]] = {
    "status": BuiltinColumn(
        label=PROPOSAL_COLUMNS["status"].label,
        cell=lambda p: str(PROPOSAL_STATUS_LABELS[p.status]),
    ),
    "created": BuiltinColumn(
        label=PROPOSAL_COLUMNS["created"].label,
        cell=lambda p: timezone.localtime(p.creation_time).date().isoformat(),
    ),
    "scheduled": BuiltinColumn(
        label=gettext_lazy("Scheduled"),
        cell=lambda p: format_field_value(value=p.is_scheduled),
    ),
}


class ProposalExportPageView(PanelExportPageView[SessionListItemDTO]):
    """Choose columns and download the filtered proposals list."""

    export_set = PanelExportSet(
        columns=PROPOSAL_COLUMN_SET,
        export_cells=PROPOSAL_EXPORT_CELLS,
        rows=_proposal_rows,
        sheet_title=gettext_lazy("Proposals"),
        filename_part="proposals",
        chooser=ExportChooser(
            tabs_partial="panel/_proposal_tabs.html",
            page_title=gettext_lazy("Export proposals"),
            help_text=gettext_lazy(
                "Tick the columns the file gets, and order them top to bottom."
                " Every proposal the list's current filters match is exported,"
                " not just the page on screen."
            ),
        ),
    )


DISCOUNT_EXPORT_CELLS: dict[str, BuiltinColumn[FacilitatorListItemDTO]] = {
    "discount_kind": BuiltinColumn(label=gettext_lazy("Discount kind")),
    "discount_value": BuiltinColumn(label=gettext_lazy("Discount value")),
    "discount_note": BuiltinColumn(label=gettext_lazy("Note")),
}

SCHEDULE_EXPORT_CELLS: dict[str, BuiltinColumn[FacilitatorListItemDTO]] = {
    "scheduled_sessions": BuiltinColumn(label=gettext_lazy("Scheduled sessions")),
    "scheduled_hours": BuiltinColumn(label=gettext_lazy("Scheduled hours")),
}

FACILITATOR_EXPORT_CELLS: dict[str, BuiltinColumn[FacilitatorListItemDTO]] = {
    "guild": BuiltinColumn(
        label=FACILITATOR_COLUMNS["guild"].label,
        cell=lambda f: f.guild.name if f.guild is not None else "",
    ),
    **SCHEDULE_EXPORT_CELLS,
    **DISCOUNT_EXPORT_CELLS,
}


def _facilitator_computed(
    *, request: PanelRequest, event_pk: int, keys: set[str]
) -> dict[int, dict[str, str]]:
    # One call per source, never per row; a source nobody ticked costs nothing.
    computed: defaultdict[int, dict[str, str]] = defaultdict(dict)
    discounts = request.services.discounts
    if keys & DISCOUNT_EXPORT_CELLS.keys():
        for discount in discounts.list_discounts(event_pk):
            computed[discount.facilitator_id].update(
                discount_kind=str(DISCOUNT_KIND_LABELS[discount.kind]),
                discount_value=str(discount.value),
                discount_note=discount.note,
            )
    if keys & SCHEDULE_EXPORT_CELLS.keys():
        for row in discounts.list_facilitator_schedule(event_pk):
            computed[row.facilitator_id].update(
                scheduled_sessions=str(row.session_count),
                scheduled_hours=f"{row.minutes / MINUTES_PER_HOUR:g}",
            )
    return computed


def _roster_rows(
    *,
    request: PanelRequest,
    event_pk: int,
    columns: Sequence[PanelColumnDTO],
    query: FacilitatorListQuery,
) -> ExportRows[FacilitatorListItemDTO]:
    panel = request.services.facilitator_panel
    facilitators = panel.list_context(event_id=event_pk, query=query).facilitators
    keys = {column.key for column in columns}
    if "guild" in keys:
        attach_facilitator_guild_marks(
            facilitators,
            guilds=request.services.guilds,
            sphere_id=request.context.current_sphere_id,
        )
    return ExportRows(
        rows=facilitators,
        raw_values=panel.column_values(
            facilitator_ids=[f.pk for f in facilitators],
            field_ids=[c.field.pk for c in columns if c.field is not None],
        ),
        computed=_facilitator_computed(request=request, event_pk=event_pk, keys=keys),
    )


def _facilitator_rows(
    *, request: PanelRequest, event_pk: int, columns: Sequence[PanelColumnDTO]
) -> ExportRows[FacilitatorListItemDTO]:
    return _roster_rows(
        request=request,
        event_pk=event_pk,
        columns=columns,
        query=read_facilitator_query(request),
    )


def _discount_rows(
    *, request: PanelRequest, event_pk: int, columns: Sequence[PanelColumnDTO]
) -> ExportRows[FacilitatorListItemDTO]:
    return _roster_rows(
        request=request,
        event_pk=event_pk,
        columns=columns,
        query=read_discount_query(request),
    )


class FacilitatorExportPageView(PanelExportPageView[FacilitatorListItemDTO]):
    """Choose columns and download the filtered facilitators list."""

    export_set = PanelExportSet(
        columns=FACILITATOR_COLUMN_SET,
        export_cells=FACILITATOR_EXPORT_CELLS,
        rows=_facilitator_rows,
        sheet_title=gettext_lazy("Facilitators"),
        filename_part="facilitators",
        chooser=ExportChooser(
            tabs_partial="panel/_facilitator_tabs.html",
            page_title=gettext_lazy("Export facilitators"),
            help_text=gettext_lazy(
                "Tick the columns the file gets, and order them top to bottom."
                " Every facilitator the list's current filters match is"
                " exported, not just the page on screen."
            ),
        ),
    )


class DiscountExportPageView(PanelExportPageView[FacilitatorListItemDTO]):
    """Download the accreditation sheet: the filtered roster with its discounts."""

    # The same rows as the facilitators list — the roster *is* a facilitator
    # list — narrowed by the one filter the roster page offers and fixed to the
    # four desk columns.
    export_set = PanelExportSet(
        columns=FACILITATOR_COLUMN_SET,
        export_cells=DISCOUNT_EXPORT_CELLS,
        rows=_discount_rows,
        sheet_title=gettext_lazy("Accreditation sheet"),
        filename_part="accreditation",
        # The desk sheet has no chooser and no stored columns of its own.
        default_keys=("name", "discount_kind", "discount_value", "discount_note"),
    )
