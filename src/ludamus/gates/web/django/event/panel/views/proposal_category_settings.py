from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.event.panel.forms import parse_requirement_selection
from ludamus.gates.web.django.event.panel.views.base import (
    EventContextMixin,
    EventPanelAccessMixin,
    EventPanelRequest,
)
from ludamus.gates.web.django.forms import ProposalCategoryForm
from ludamus.pacts.legacy import NotFoundError, PromotionMode
from ludamus.pacts.submissions import (
    ProposalCategoryEditContextDTO,
    ProposalCategorySettingsData,
)

if TYPE_CHECKING:
    from django.http import HttpResponse


def _form(page: ProposalCategoryEditContextDTO) -> ProposalCategoryForm:
    category = page.category
    return ProposalCategoryForm(
        initial={
            "name": category.name,
            "description": category.description,
            "start_time": category.start_time,
            "end_time": category.end_time,
            "min_participants_limit": category.min_participants_limit,
            "max_participants_limit": category.max_participants_limit,
            "promotion_mode": category.promotion_mode.value,
            "offer_claim_window_minutes": int(
                category.offer_claim_window.total_seconds() // 60
            ),
        }
    )


def _settings_data(
    request: EventPanelRequest, form: ProposalCategoryForm
) -> ProposalCategorySettingsData:
    cleaned = form.cleaned_data
    return ProposalCategorySettingsData(
        name=cleaned["name"],
        description=cleaned["description"],
        start_time=cleaned["start_time"],
        end_time=cleaned["end_time"],
        durations=[
            duration for duration in request.POST.getlist("durations") if duration
        ],
        min_participants_limit=cleaned["min_participants_limit"] or 0,
        max_participants_limit=cleaned["max_participants_limit"] or 0,
        promotion_mode=(
            PromotionMode(cleaned["promotion_mode"])
            if cleaned.get("promotion_mode")
            else None
        ),
        offer_claim_window=(
            timedelta(minutes=cleaned["offer_claim_window_minutes"])
            if cleaned.get("offer_claim_window_minutes")
            else None
        ),
        personal_fields=parse_requirement_selection(
            request.POST, prefix="field_", order_key="field_order"
        ),
        session_fields=parse_requirement_selection(
            request.POST, prefix="session_field_", order_key="session_field_order"
        ),
        time_slots=parse_requirement_selection(
            request.POST, prefix="time_slot_", order_key="time_slot_order"
        ),
    )


def _render(
    *,
    request: EventPanelRequest,
    context: dict[str, object],
    page: ProposalCategoryEditContextDTO,
    form: ProposalCategoryForm,
) -> TemplateResponse:
    context.update(
        active_nav="cfp",
        category=page.category,
        form=form,
        available_fields=page.available_fields,
        field_requirements=page.field_requirements,
        field_order=page.field_order,
        available_session_fields=page.available_session_fields,
        session_field_requirements=page.session_field_requirements,
        session_field_order=page.session_field_order,
        available_time_slots=page.available_time_slots,
        time_slot_requirements=page.time_slot_requirements,
        time_slot_order=page.time_slot_order,
        durations=page.category.durations,
        proposal_count=page.proposal_count,
    )
    return TemplateResponse(request, "panel/cfp-edit.html", context)


class ProposalCategorySettingsPageView(EventPanelAccessMixin, EventContextMixin, View):
    request: EventPanelRequest

    def get(
        self, _request: EventPanelRequest, event_slug: str, category_slug: str
    ) -> HttpResponse:
        context, current_event = self.get_event_context(event_slug)
        if current_event is None:
            return redirect("panel:index")
        try:
            page = self.request.services.proposal_category_settings.read_context(
                current_event.pk, category_slug
            )
        except NotFoundError:
            return self._category_not_found(event_slug)
        return _render(
            request=self.request, context=context, page=page, form=_form(page)
        )

    def post(
        self, _request: EventPanelRequest, event_slug: str, category_slug: str
    ) -> HttpResponse:
        context, current_event = self.get_event_context(event_slug)
        if current_event is None:
            return redirect("panel:index")

        form = ProposalCategoryForm(self.request.POST)
        if not form.is_valid():
            try:
                page = self.request.services.proposal_category_settings.read_context(
                    current_event.pk, category_slug
                )
            except NotFoundError:
                return self._category_not_found(event_slug)
            return _render(request=self.request, context=context, page=page, form=form)

        try:
            self.request.services.proposal_category_settings.update(
                event_id=current_event.pk,
                category_slug=category_slug,
                data=_settings_data(self.request, form),
            )
        except NotFoundError:
            return self._category_not_found(event_slug)
        messages.success(self.request, _("Category updated successfully."))
        return redirect("panel:cfp", slug=event_slug)

    def _category_not_found(self, event_slug: str) -> HttpResponse:
        messages.error(self.request, _("Category not found."))
        return redirect("panel:cfp", slug=event_slug)
