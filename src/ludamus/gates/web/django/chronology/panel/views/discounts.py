from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.adapters.db.django.models import AccreditationType
from ludamus.gates.web.django.chronology.panel.views.base import (
    EventContextMixin,
    PanelAccessMixin,
    PanelRequest,
)
from ludamus.gates.web.django.forms import DiscountForm
from ludamus.pacts import NotFoundError
from ludamus.pacts.discounts import DiscountData, DiscountKind

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.pacts import FacilitatorDTO
    from ludamus.pacts.discounts import DiscountDTO


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


class DiscountsPageView(PanelAccessMixin, EventContextMixin, View):
    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        facilitators = self.request.di.uow.facilitators.list_by_event(current_event.pk)
        discounts_by_facilitator = {
            discount.facilitator_id: discount
            for discount in self.request.services.discounts.list_by_event(
                current_event.pk
            )
        }
        rows = [
            {
                "facilitator": facilitator,
                "accreditation_type_display": (
                    AccreditationType(facilitator.accreditation_type).label
                ),
                "discount": discounts_by_facilitator.get(facilitator.pk),
            }
            for facilitator in facilitators
        ]

        context["active_nav"] = "discounts"
        context["rows"] = rows
        return TemplateResponse(self.request, "panel/discounts/list.html", context)


class DiscountCreatePageView(PanelAccessMixin, EventContextMixin, View):
    request: PanelRequest

    def get(
        self, _request: PanelRequest, slug: str, facilitator_id: int
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

        context["active_nav"] = "discounts"
        context["facilitator"] = facilitator
        context["form"] = DiscountForm()
        return TemplateResponse(self.request, "panel/discounts/create.html", context)

    def post(
        self, _request: PanelRequest, slug: str, facilitator_id: int
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
            context["active_nav"] = "discounts"
            context["facilitator"] = facilitator
            context["form"] = form
            return TemplateResponse(
                self.request, "panel/discounts/create.html", context
            )

        self.request.services.discounts.create(
            current_event.pk, _form_data(form, facilitator_id)
        )
        messages.success(self.request, _("Discount assigned successfully."))
        return redirect("panel:discounts", slug=slug)


class DiscountEditPageView(PanelAccessMixin, EventContextMixin, View):
    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
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

    def post(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
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

    def post(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
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
