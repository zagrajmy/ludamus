from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.generic.base import View

from ludamus.gates.web.django.chronology.panel.views.base import (
    EventContextMixin,
    PanelAccessMixin,
    PanelRequest,
)
from ludamus.gates.web.django.chronology.panel.views.columns import (
    FACILITATOR_COLUMNS,
    column_views,
    facilitator_column_values,
)
from ludamus.gates.web.django.forms import (
    ACCREDITATION_TYPE_LABELS,
    DISCOUNT_KIND_LABELS,
    DiscountExportForm,
    DiscountForm,
)
from ludamus.gates.web.django.panel import PanelNavContext
from ludamus.pacts import NotFoundError
from ludamus.pacts.discounts import (
    DiscountData,
    DiscountExportColumns,
    DiscountExportLabels,
    DiscountKind,
)
from ludamus.pacts.sheets import SheetExportError
from ludamus.pacts.submissions import AccreditationType

if TYPE_CHECKING:
    from django.http import HttpResponse
    from django.utils.functional import Promise

    from ludamus.pacts import FacilitatorDTO, FacilitatorListItemDTO
    from ludamus.pacts.discounts import DiscountDTO
    from ludamus.pacts.panel import PanelColumnDTO


class _DiscountAssignment(TypedDict):
    facilitator: FacilitatorListItemDTO
    form: DiscountForm


class _DiscountRow(TypedDict):
    facilitator: FacilitatorListItemDTO
    accreditation_type_display: str | Promise
    discount: DiscountDTO | None


class _DiscountsContext(PanelNavContext):
    assignments: list[_DiscountAssignment]
    rows: list[_DiscountRow]


def _form_data(form: DiscountForm, facilitator_id: int) -> DiscountData:
    return DiscountData(
        facilitator_id=facilitator_id,
        kind=DiscountKind(form.cleaned_data["kind"]),
        value=form.cleaned_data["value"],
        note=form.cleaned_data["note"],
        # Hand-assigned: the rule sync leaves this discount alone.
        from_rules=False,
    )


def _scoped_discount(
    *, request: PanelRequest, event_pk: int, pk: int
) -> DiscountDTO | None:
    try:
        return request.services.discounts.read_scoped(event_pk=event_pk, pk=pk)
    except NotFoundError:
        return None


def _scoped_facilitator(
    *, request: PanelRequest, event_pk: int, facilitator_id: int
) -> FacilitatorDTO | None:
    try:
        return request.services.discounts.read_scoped_facilitator(
            event_pk=event_pk, facilitator_id=facilitator_id
        )
    except NotFoundError:
        return None


def _discounts_context(
    *,
    request: PanelRequest,
    event_pk: int,
    assign_facilitator_id: int | None = None,
    assign_form: DiscountForm | None = None,
) -> _DiscountsContext:
    rows: list[_DiscountRow] = []
    assignments: list[_DiscountAssignment] = []
    for entry in request.services.discounts.list_roster(event_pk):
        facilitator = entry.facilitator
        rows.append(
            {
                "facilitator": facilitator,
                "accreditation_type_display": ACCREDITATION_TYPE_LABELS[
                    AccreditationType(facilitator.accreditation_type)
                ],
                "discount": entry.discount,
            }
        )
        if entry.discount is None:
            form = (
                assign_form
                if facilitator.pk == assign_facilitator_id and assign_form is not None
                else DiscountForm(auto_id=f"discount_{facilitator.pk}_%s")
            )
            assignments.append({"facilitator": facilitator, "form": form})
    return {"active_nav": "discounts", "assignments": assignments, "rows": rows}


class DiscountsPageView(PanelAccessMixin, EventContextMixin, View):
    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        context.update(
            _discounts_context(request=self.request, event_pk=current_event.pk)
        )
        return TemplateResponse(self.request, "panel/discounts/list.html", context)


class DiscountCreatePageView(PanelAccessMixin, EventContextMixin, View):
    request: PanelRequest

    def get(
        self, _request: PanelRequest, *, slug: str, facilitator_id: int
    ) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        facilitator = _scoped_facilitator(
            request=self.request,
            event_pk=current_event.pk,
            facilitator_id=facilitator_id,
        )
        if facilitator is None:
            messages.error(self.request, _("Facilitator not found."))
            return redirect("panel:discounts", slug=slug)

        discounts_url = reverse("panel:discounts", kwargs={"slug": slug})
        return redirect(f"{discounts_url}?assign={facilitator_id}")

    def post(
        self, _request: PanelRequest, *, slug: str, facilitator_id: int
    ) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        facilitator = _scoped_facilitator(
            request=self.request,
            event_pk=current_event.pk,
            facilitator_id=facilitator_id,
        )
        if facilitator is None:
            messages.error(self.request, _("Facilitator not found."))
            return redirect("panel:discounts", slug=slug)

        form = DiscountForm(self.request.POST)
        if not form.is_valid():
            context.update(
                _discounts_context(
                    request=self.request,
                    event_pk=current_event.pk,
                    assign_facilitator_id=facilitator_id,
                    assign_form=form,
                )
            )
            return TemplateResponse(self.request, "panel/discounts/list.html", context)

        self.request.services.discounts.create(
            current_event.pk, _form_data(form, facilitator_id)
        )
        messages.success(self.request, _("Discount assigned successfully."))
        return redirect("panel:discounts", slug=slug)


class DiscountEditPageView(PanelAccessMixin, EventContextMixin, View):
    request: PanelRequest

    def get(self, _request: PanelRequest, *, slug: str, pk: int) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        discount = _scoped_discount(
            request=self.request, event_pk=current_event.pk, pk=pk
        )
        if discount is None:
            messages.error(self.request, _("Discount not found."))
            return redirect("panel:discounts", slug=slug)

        context["active_nav"] = "discounts"
        context["discount"] = discount
        context["form"] = DiscountForm(
            initial={
                "kind": discount.kind,
                "value": discount.value,
                "note": discount.note,
            }
        )
        return TemplateResponse(self.request, "panel/discounts/edit.html", context)

    def post(self, _request: PanelRequest, *, slug: str, pk: int) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        discount = _scoped_discount(
            request=self.request, event_pk=current_event.pk, pk=pk
        )
        if discount is None:
            messages.error(self.request, _("Discount not found."))
            return redirect("panel:discounts", slug=slug)

        form = DiscountForm(self.request.POST)
        if not form.is_valid():
            context["active_nav"] = "discounts"
            context["discount"] = discount
            context["form"] = form
            return TemplateResponse(self.request, "panel/discounts/edit.html", context)

        self.request.services.discounts.update(
            pk, _form_data(form, discount.facilitator_id)
        )
        messages.success(self.request, _("Discount updated successfully."))
        return redirect("panel:discounts", slug=slug)


class DiscountDeleteActionView(PanelAccessMixin, EventContextMixin, View):
    request: PanelRequest

    def post(self, _request: PanelRequest, *, slug: str, pk: int) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        discount = _scoped_discount(
            request=self.request, event_pk=current_event.pk, pk=pk
        )
        if discount is None:
            messages.error(self.request, _("Discount not found."))
            return redirect("panel:discounts", slug=slug)

        self.request.services.discounts.soft_delete(pk)
        messages.success(self.request, _("Discount removed successfully."))
        return redirect("panel:discounts", slug=slug)


class DiscountSyncActionView(PanelAccessMixin, EventContextMixin, View):
    """Re-derive creator accreditation and rule discounts from the agenda."""

    request: PanelRequest
    http_method_names = ("post",)

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        result = self.request.services.discounts.apply_from_agenda(
            event_pk=current_event.pk, user_id=self.request.context.current_user_id
        )
        messages.success(
            self.request,
            _(
                "Agenda applied — marked as creators: %(marked)d, unmarked:"
                " %(unmarked)d, discounts assigned: %(set)d, discounts withdrawn:"
                " %(cleared)d."
            )
            % {
                "marked": result.marked,
                "unmarked": result.unmarked,
                "set": result.discounts_set,
                "cleared": result.discounts_cleared,
            },
        )
        return redirect("panel:discounts", slug=slug)


def _export_labels() -> DiscountExportLabels:
    return DiscountExportLabels(
        headers=[_("Discount kind"), _("Discount value"), _("Note")],
        kinds={kind.value: str(label) for kind, label in DISCOUNT_KIND_LABELS.items()},
    )


# The guild column has no cell of its own — the list renders it as a badge —
# so it has nothing to write into a sheet.
_UNEXPORTABLE_KEYS = frozenset({"guild"})


def _exportable_columns(request: PanelRequest, event_pk: int) -> list[PanelColumnDTO]:
    # Every facilitator and personal-data column the list can show. Which of
    # them the sheet gets is the organizer's call, per export: a display name
    # can be a group's name, so even that one is nobody's default.
    context = request.services.facilitator_panel.columns_context(event_pk)
    return [
        column
        for column in (*context.chosen, *context.available)
        if column.key not in _UNEXPORTABLE_KEYS
    ]


def _column_choices(request: PanelRequest, event_pk: int) -> list[tuple[str, str]]:
    views = column_views(_exportable_columns(request, event_pk), FACILITATOR_COLUMNS)
    return [(view.key, view.label) for view in views]


def _chosen_columns(
    *, request: PanelRequest, event_pk: int, keys: list[str]
) -> DiscountExportColumns:
    by_key = {column.key: column for column in _exportable_columns(request, event_pk)}
    chosen = [column for key in keys if (column := by_key.get(key))]
    # The roster is read again here rather than threaded through the export
    # service: only the gate knows what a facilitator column reads as.
    facilitators = [
        entry.facilitator for entry in request.services.discounts.list_roster(event_pk)
    ]
    values = facilitator_column_values(
        panel=request.services.facilitator_panel,
        facilitators=facilitators,
        columns=chosen,
    )
    return DiscountExportColumns(
        headers=[view.label for view in column_views(chosen, FACILITATOR_COLUMNS)],
        cells={
            facilitator.pk: [
                values.get(facilitator.pk, {}).get(column.key, "") for column in chosen
            ]
            for facilitator in facilitators
        },
    )


class DiscountExportPageView(PanelAccessMixin, EventContextMixin, View):
    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        connections = self.request.services.connections.list_for_sphere(
            self.request.context.current_sphere_id
        )
        return self._render(
            context=context,
            form=DiscountExportForm(
                connections=connections,
                columns=_column_choices(self.request, current_event.pk),
            ),
            has_connections=bool(connections),
        )

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        sphere_id = self.request.context.current_sphere_id
        connections = self.request.services.connections.list_for_sphere(sphere_id)
        form = DiscountExportForm(
            self.request.POST,
            connections=connections,
            columns=_column_choices(self.request, current_event.pk),
        )
        if not form.is_valid():
            return self._render(
                context=context, form=form, has_connections=bool(connections)
            )

        try:
            count = self.request.services.discounts_export.export_to_sheet(
                sphere_id=sphere_id,
                event_pk=current_event.pk,
                connection_id=int(form.cleaned_data["connection"]),
                spreadsheet_id=form.cleaned_data["spreadsheet"],
                tab_title=form.cleaned_data["tab"],
                labels=_export_labels(),
                columns=_chosen_columns(
                    request=self.request,
                    event_pk=current_event.pk,
                    keys=form.cleaned_data["columns"],
                ),
            )
        except NotFoundError:
            messages.error(self.request, _("Connection not found."))
            return self._render(
                context=context, form=form, has_connections=bool(connections)
            )
        except SheetExportError as error:
            messages.error(self.request, _("Export failed: %(hint)s") % {"hint": error})
            return self._render(
                context=context, form=form, has_connections=bool(connections)
            )

        messages.success(
            self.request,
            ngettext(
                "Accreditation sheet exported (%(count)d creator).",
                "Accreditation sheet exported (%(count)d creators).",
                count,
            )
            % {"count": count},
        )
        return redirect("panel:discounts", slug=slug)

    def _render(
        self,
        *,
        context: dict[str, object],
        form: DiscountExportForm,
        has_connections: bool,
    ) -> HttpResponse:
        context["active_nav"] = "discounts"
        context["form"] = form
        context["has_connections"] = has_connections
        return TemplateResponse(self.request, "panel/discounts/export.html", context)
