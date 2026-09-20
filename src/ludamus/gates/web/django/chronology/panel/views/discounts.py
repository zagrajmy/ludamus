from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.chronology.panel.views.base import (
    EventContextMixin,
    PanelAccessMixin,
    PanelRequest,
    read_accreditation_filter,
)
from ludamus.gates.web.django.forms import (
    ACCREDITATION_TYPE_CHOICES,
    ACCREDITATION_TYPE_LABELS,
    DiscountForm,
)
from ludamus.gates.web.django.panel import PanelNavContext
from ludamus.pacts import FacilitatorListItemDTO, NotFoundError
from ludamus.pacts.discounts import DiscountData, DiscountKind
from ludamus.pacts.panel import FacilitatorListQuery
from ludamus.pacts.submissions import AccreditationType

if TYPE_CHECKING:
    from django.http import HttpResponse
    from django.utils.functional import Promise, _StrPromise

    from ludamus.pacts import FacilitatorDTO
    from ludamus.pacts.discounts import DiscountDTO


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
    filters_active: bool
    accreditation_types: list[tuple[str, _StrPromise]]


def read_discount_query(request: PanelRequest) -> FacilitatorListQuery:
    # The roster page renders one filter, so it reads one: a facilitator-list
    # filter the page cannot show would narrow both the roster and its
    # accreditation sheet with nothing on screen to clear it by.
    return FacilitatorListQuery(
        accreditation=read_accreditation_filter(request),
        current_user_id=request.context.current_user_id,
    )


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
    # The roster is a facilitator list, so it is the facilitators list: the same
    # query DTO the mill applies, the same rows and order, and the accreditation
    # sheet reads it through the same reader. Everyone the event knows has a
    # line — accreditation NONE included — because the desk sheet listing only
    # the discounted was a hidden rule no filter could express (plans/020).
    query = read_discount_query(request)
    facilitators = request.services.facilitator_panel.list_context(
        event_id=event_pk, query=query
    ).facilitators
    discounts = {
        discount.facilitator_id: discount
        for discount in request.services.discounts.list_discounts(event_pk)
    }
    rows: list[_DiscountRow] = []
    assignments: list[_DiscountAssignment] = []
    for facilitator in facilitators:
        discount = discounts.get(facilitator.pk)
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
    return {
        "active_nav": "discounts",
        "assignments": assignments,
        "rows": rows,
        "filter_accreditation": query.accreditation,
        "filters_active": bool(query.accreditation),
        "accreditation_types": ACCREDITATION_TYPE_CHOICES,
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
