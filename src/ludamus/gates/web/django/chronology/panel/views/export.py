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
from ludamus.pacts.panel import PanelColumnDTO, PanelColumnsContextDTO

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from django.utils.functional import _StrPromise

    from ludamus.pacts.discounts import DiscountDTO

ODS_CONTENT_TYPE = "application/vnd.oasis.opendocument.spreadsheet"


@dataclass(frozen=True)
class ExportRows[RowT: PanelRowProtocol]:
    """The full filtered result and the values its cells read from."""

    rows: Sequence[RowT]
    raw_values: Mapping[int, Mapping[str, str | list[str] | bool]]
    # Values a row cannot supply itself, keyed by row pk then column key.
    computed: Mapping[int, Mapping[str, str]] = field(default_factory=dict)


class ExportRowsProtocol[RowT: PanelRowProtocol](Protocol):
    def __call__(
        self,
        *,
        view: EventContextMixin,
        event_pk: int,
        columns: Sequence[PanelColumnDTO],
    ) -> ExportRows[RowT]: ...


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
    template: str | None = None
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
        template = self.export_set.template
        if template is not None and not submitted:
            return self._render(
                template=template,
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
        if not columns and template is not None:
            return self._render(
                template=template,
                context=context,
                slug=slug,
                event_pk=current_event.pk,
                error=_("Pick at least one column to export."),
            )
        return self._download(slug=slug, event_pk=current_event.pk, columns=columns)

    def _render(
        self,
        *,
        template: str,
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
        return TemplateResponse(self.request, template, context)

    def _download(
        self, *, slug: str, event_pk: int, columns: Sequence[PanelColumnDTO]
    ) -> HttpResponse:
        loaded = self.export_set.rows(view=self, event_pk=event_pk, columns=columns)
        cells = column_values(
            rows=loaded.rows,
            columns=columns,
            builtins=self.export_set.cells,
            raw_values=loaded.raw_values,
        )
        headers = [view.label for view in column_views(columns, self.export_set.cells)]
        body = [
            [
                {**cells.get(row.pk, {}), **loaded.computed.get(row.pk, {})}.get(
                    column.key, ""
                )
                for column in columns
            ]
            for row in loaded.rows
        ]
        content = spreadsheet_bytes(
            rows=[headers, *body], sheet_title=str(self.export_set.sheet_title)
        )
        response = HttpResponse(content, content_type=ODS_CONTENT_TYPE)
        filename = f"{slug}-{self.export_set.filename_part}-{timezone.localdate()}.ods"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


def _proposal_rows(
    *, view: EventContextMixin, event_pk: int, columns: Sequence[PanelColumnDTO]
) -> ExportRows[SessionListItemDTO]:
    _tracks, _managed, track_pk = view.get_track_filter_context(event_pk)
    query = read_proposal_query(view.request, track_pk=track_pk)
    panel = view.request.services.proposal_panel
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
        template="panel/proposal-export.html",
    )


DISCOUNT_EXPORT_CELLS: dict[str, BuiltinColumn[FacilitatorListItemDTO]] = {
    "discount_kind": BuiltinColumn(label=gettext_lazy("Discount kind")),
    "discount_value": BuiltinColumn(label=gettext_lazy("Discount value")),
    "discount_note": BuiltinColumn(label=gettext_lazy("Note")),
}

_SCHEDULE_KEYS = frozenset({"scheduled_sessions", "scheduled_hours"})

FACILITATOR_EXPORT_CELLS: dict[str, BuiltinColumn[FacilitatorListItemDTO]] = {
    "guild": BuiltinColumn(
        label=FACILITATOR_COLUMNS["guild"].label,
        cell=lambda f: f.guild.name if f.guild is not None else "",
    ),
    "scheduled_sessions": BuiltinColumn(label=gettext_lazy("Scheduled sessions")),
    "scheduled_hours": BuiltinColumn(label=gettext_lazy("Scheduled hours")),
    **DISCOUNT_EXPORT_CELLS,
}


def discount_cells(discount: DiscountDTO | None) -> dict[str, str]:
    if discount is None:
        return {}
    return {
        "discount_kind": str(DISCOUNT_KIND_LABELS[discount.kind]),
        "discount_value": str(discount.value),
        "discount_note": discount.note,
    }


def _facilitator_computed(
    *, request: PanelRequest, event_pk: int, keys: set[str]
) -> dict[int, dict[str, str]]:
    # One call per source, never per row; a source nobody ticked costs nothing.
    computed: defaultdict[int, dict[str, str]] = defaultdict(dict)
    discounts = request.services.discounts
    if keys & DISCOUNT_EXPORT_CELLS.keys():
        for entry in discounts.list_roster(event_pk):
            computed[entry.facilitator.pk].update(discount_cells(entry.discount))
    if keys & _SCHEDULE_KEYS:
        for row in discounts.list_facilitator_schedule(event_pk):
            computed[row.facilitator_id].update(
                scheduled_sessions=str(row.session_count),
                scheduled_hours=f"{row.minutes / MINUTES_PER_HOUR:g}",
            )
    return computed


def _facilitator_rows(
    *, view: EventContextMixin, event_pk: int, columns: Sequence[PanelColumnDTO]
) -> ExportRows[FacilitatorListItemDTO]:
    panel = view.request.services.facilitator_panel
    facilitators = panel.list_context(
        event_id=event_pk, query=read_facilitator_query(view.request)
    ).facilitators
    attach_facilitator_guild_marks(
        facilitators,
        guilds=view.request.services.guilds,
        sphere_id=view.request.context.current_sphere_id,
    )
    return ExportRows(
        rows=facilitators,
        raw_values=panel.column_values(
            facilitator_ids=[f.pk for f in facilitators],
            field_ids=[c.field.pk for c in columns if c.field is not None],
        ),
        computed=_facilitator_computed(
            request=view.request,
            event_pk=event_pk,
            keys={column.key for column in columns},
        ),
    )


class FacilitatorExportPageView(PanelExportPageView[FacilitatorListItemDTO]):
    """Choose columns and download the filtered facilitators list."""

    export_set = PanelExportSet(
        columns=FACILITATOR_COLUMN_SET,
        export_cells=FACILITATOR_EXPORT_CELLS,
        rows=_facilitator_rows,
        sheet_title=gettext_lazy("Facilitators"),
        filename_part="facilitators",
        template="panel/facilitator-export.html",
    )
