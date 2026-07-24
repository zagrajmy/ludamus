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
from ludamus.gates.web.django.forms import (
    ACCREDITATION_TYPE_LABELS,
    DISCOUNT_KIND_LABELS,
    DiscountExportForm,
    DiscountForm,
)
from ludamus.pacts import NotFoundError
from ludamus.pacts.discounts import (
    DiscountData,
    DiscountExportLabels,
    DiscountKind,
    SheetExportError,
)
from ludamus.pacts.submissions import AccreditationType

if TYPE_CHECKING:
    from django.http import HttpResponse
    from django.utils.functional import Promise

    from ludamus.pacts import FacilitatorDTO, FacilitatorListItemDTO
    from ludamus.pacts.discounts import DiscountDTO


class _DiscountAssignment(TypedDict):
    facilitator: FacilitatorListItemDTO
    form: DiscountForm


class _DiscountRow(TypedDict):
    facilitator: FacilitatorListItemDTO
    accreditation_type_display: str | Promise
    discount: DiscountDTO | None


class _DiscountsContext(TypedDict):
    active_nav: str
    assignments: list[_DiscountAssignment]
    rows: list[_DiscountRow]


def _form_data(form: DiscountForm, facilitator_id: int) -> DiscountData:
    return DiscountData(
        facilitator_id=facilitator_id,
        kind=DiscountKind(form.cleaned_data["kind"]),
        value=form.cleaned_data["value"],
        note=form.cleaned_data["note"],
    )


def _scoped_discount(
    *, request: PanelRequest, event_pk: int, pk: int
) -> DiscountDTO | None:
    try:
        discount = request.services.discounts.get(pk)
    except NotFoundError:
        return None
    return discount if discount.event_id == event_pk else None


def _scoped_facilitator(
    *, request: PanelRequest, event_pk: int, facilitator_id: int
) -> FacilitatorDTO | None:
    try:
        facilitator = request.di.uow.facilitators.read(facilitator_id)
    except NotFoundError:
        return None
    return facilitator if facilitator.event_id == event_pk else None


def _discounts_context(
    *,
    request: PanelRequest,
    event_pk: int,
    assign_facilitator_id: int | None = None,
    assign_form: DiscountForm | None = None,
) -> _DiscountsContext:
    facilitators = request.di.uow.facilitators.list_by_event(event_pk)
    discounts_by_facilitator = {
        discount.facilitator_id: discount
        for discount in request.services.discounts.list_by_event(event_pk)
    }
    rows: list[_DiscountRow] = []
    assignments: list[_DiscountAssignment] = []
    for facilitator in facilitators:
        discount = discounts_by_facilitator.get(facilitator.pk)
        rows.append(
            {
                "facilitator": facilitator,
                "accreditation_type_display": ACCREDITATION_TYPE_LABELS[
                    AccreditationType(facilitator.accreditation_type)
                ],
                "discount": discount,
            }
        )
        if discount is None:
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


def _export_labels() -> DiscountExportLabels:
    return DiscountExportLabels(
        headers=[
            _("Creator"),
            _("Accreditation type"),
            _("Discount kind"),
            _("Discount value"),
            _("Note"),
        ],
        accreditation_types={
            t.value: str(label) for t, label in ACCREDITATION_TYPE_LABELS.items()
        },
        kinds={kind.value: str(label) for kind, label in DISCOUNT_KIND_LABELS.items()},
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
            form=DiscountExportForm(connections=connections),
            has_connections=bool(connections),
        )

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        sphere_id = self.request.context.current_sphere_id
        connections = self.request.services.connections.list_for_sphere(sphere_id)
        form = DiscountExportForm(self.request.POST, connections=connections)
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
                labels=_export_labels(),
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
