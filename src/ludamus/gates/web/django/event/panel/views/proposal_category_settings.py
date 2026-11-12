from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.event.panel.views.base import EventPanelMixin
from ludamus.gates.web.django.forms import ProposalCategoryForm
from ludamus.gates.web.django.panel import PanelRequest, parse_requirement_selection
from ludamus.gates.web.django.redirects import RedirectError
from ludamus.pacts.durations import normalize_duration
from ludamus.pacts.enrollment import PromotionMode
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.propose import (
    ProposalCategoryEditContextDTO,
    ProposalCategorySettingsData,
)

if TYPE_CHECKING:
    from django.http import HttpResponse


def _category_not_found(event_slug: str) -> RedirectError:
    return RedirectError(
        reverse("panel:cfp", kwargs={"slug": event_slug}),
        error=_("Category not found."),
    )


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
    request: PanelRequest, form: ProposalCategoryForm
) -> ProposalCategorySettingsData:
    cleaned = form.cleaned_data
    return ProposalCategorySettingsData(
        name=cleaned["name"],
        description=cleaned["description"],
        start_time=cleaned["start_time"],
        end_time=cleaned["end_time"],
        # The steppers compose ISO already, but a duration saved before they
        # existed can still be posted back — normalize so only readable lengths
        # are stored.
        durations=[
            normalized
            for duration in request.POST.getlist("durations")
            if (normalized := normalize_duration(duration))
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
        session_fields=parse_requirement_selection(
            request.POST, prefix="session_field_", order_key="session_field_order"
        ),
        asks_availability=bool(request.POST.get("asks_availability")),
    )


def _render(
    *,
    request: PanelRequest,
    context: dict[str, object],
    page: ProposalCategoryEditContextDTO,
    form: ProposalCategoryForm,
) -> TemplateResponse:
    context.update(
        active_nav="cfp",
        category=page.category,
        form=form,
        available_session_fields=page.available_session_fields,
        session_field_requirements=page.session_field_requirements,
        session_field_order=page.session_field_order,
        asks_availability=page.asks_availability,
        durations=page.category.durations,
        proposal_count=page.proposal_count,
    )
    return TemplateResponse(request, "panel/cfp-edit.html", context)


class ProposalCategorySettingsPageView(EventPanelMixin, View):
    request: PanelRequest
    event_slug_kwarg = "event_slug"

    def get(
        self, _request: PanelRequest, event_slug: str, category_slug: str
    ) -> HttpResponse:
        context = self.panel_context()
        page = self._read_page(self.current_event.pk, category_slug, event_slug)
        return _render(
            request=self.request, context=context, page=page, form=_form(page)
        )

    def post(
        self, _request: PanelRequest, event_slug: str, category_slug: str
    ) -> HttpResponse:
        context = self.panel_context()
        form = ProposalCategoryForm(self.request.POST)
        if not form.is_valid():
            page = self._read_page(self.current_event.pk, category_slug, event_slug)
            return _render(request=self.request, context=context, page=page, form=form)

        try:
            self.request.services.proposal_category_settings.update(
                event_id=self.current_event.pk,
                category_slug=category_slug,
                data=_settings_data(self.request, form),
            )
        except NotFoundError as error:
            raise _category_not_found(event_slug) from error
        messages.success(self.request, _("Category updated successfully."))
        return redirect("panel:cfp", slug=event_slug)

    def _read_page(
        self, event_pk: int, category_slug: str, event_slug: str
    ) -> ProposalCategoryEditContextDTO:
        try:
            return self.request.services.proposal_category_settings.read_context(
                event_pk, category_slug
            )
        except NotFoundError as error:
            raise _category_not_found(event_slug) from error
