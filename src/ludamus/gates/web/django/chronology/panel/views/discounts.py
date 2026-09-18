from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.generic.base import View

from ludamus.gates.web.django.chronology.panel.views.base import (
    EventContextMixin,
    PanelAccessMixin,
    PanelRequest,
    accreditation_filter,
)
from ludamus.gates.web.django.chronology.panel.views.columns import (
    FACILITATOR_COLUMN_SET,
)
from ludamus.gates.web.django.chronology.panel.views.export import (
    DISCOUNT_EXPORT_CELLS,
    ExportRows,
    PanelExportPageView,
    PanelExportSet,
    discount_cells,
)
from ludamus.gates.web.django.forms import ACCREDITATION_TYPE_LABELS, DiscountForm
from ludamus.gates.web.django.panel import PanelNavContext
from ludamus.pacts import FacilitatorListItemDTO, NotFoundError
from ludamus.pacts.discounts import DiscountData, DiscountKind
from ludamus.pacts.submissions import AccreditationType

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.http import HttpResponse
    from django.utils.functional import Promise, _StrPromise

    from ludamus.pacts import FacilitatorDTO
    from ludamus.pacts.discounts import DiscountDTO, DiscountRosterEntryDTO
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
    filter_accreditation: str
    accreditation_types: list[tuple[str, _StrPromise]]


def filtered_roster(
    *, request: PanelRequest, event_pk: int
) -> list[DiscountRosterEntryDTO]:
    # The list and its export read the same filter, so the sheet holds exactly
    # the rows on screen — people who get nothing at the desk included, unless
    # the organizer filtered them out.
    accreditation = accreditation_filter(request).value
    return [
        entry
        for entry in request.services.discounts.list_roster(event_pk)
        if not accreditation or entry.facilitator.accreditation_type == accreditation
    ]


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
    for entry in filtered_roster(request=request, event_pk=event_pk):
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
    accreditation = accreditation_filter(request)
    return {
        "active_nav": "discounts",
        "assignments": assignments,
        "rows": rows,
        "filter_accreditation": accreditation.value,
        "accreditation_types": accreditation.options,
    }


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


def _discount_rows(
    *, view: EventContextMixin, event_pk: int, columns: Sequence[PanelColumnDTO]
) -> ExportRows[FacilitatorListItemDTO]:
    roster = filtered_roster(request=view.request, event_pk=event_pk)
    facilitators = [entry.facilitator for entry in roster]
    return ExportRows(
        rows=facilitators,
        raw_values=view.request.services.facilitator_panel.column_values(
            facilitator_ids=[f.pk for f in facilitators],
            field_ids=[c.field.pk for c in columns if c.field is not None],
        ),
        computed={
            entry.facilitator.pk: discount_cells(entry.discount) for entry in roster
        },
    )


class DiscountExportPageView(PanelExportPageView[FacilitatorListItemDTO]):
    """Download the accreditation sheet: the filtered roster with its discounts."""

    export_set = PanelExportSet(
        columns=FACILITATOR_COLUMN_SET,
        export_cells=DISCOUNT_EXPORT_CELLS,
        rows=_discount_rows,
        sheet_title=gettext_lazy("Accreditation sheet"),
        filename_part="accreditation",
        # The desk sheet has no chooser and no stored columns of its own.
        default_keys=("name", "discount_kind", "discount_value", "discount_note"),
    )
