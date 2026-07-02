"""CFP (proposal categories) views."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.chronology.panel.views.base import (
    EventContextMixin,
    PanelAccessMixin,
    PanelRequest,
    cfp_tab_urls,
)
from ludamus.gates.web.django.chronology.panel.views.fields import (
    scoped_requirements,
    sort_fields_by_order,
)
from ludamus.gates.web.django.forms import ProposalCategoryForm
from ludamus.mills import PanelService
from ludamus.pacts import NotFoundError

if TYPE_CHECKING:
    from django.http import HttpResponse


class CFPPageView(PanelAccessMixin, EventContextMixin, View):
    """List call for proposals categories for an event."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        """Display CFP categories list.

        Returns:
            TemplateResponse with the categories list or redirect if not found.
        """
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        context["active_nav"] = "cfp"
        context["active_tab"] = "types"
        context["tab_urls"] = cfp_tab_urls(slug)
        context["categories"] = self.request.di.uow.proposal_categories.list_by_event(
            current_event.pk
        )
        context["category_stats"] = (
            self.request.di.uow.proposal_categories.get_category_stats(current_event.pk)
        )
        return TemplateResponse(self.request, "panel/cfp.html", context)


class CFPCreatePageView(PanelAccessMixin, EventContextMixin, View):
    """Create a new CFP category for an event."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        """Display the CFP category creation form.

        Returns:
            TemplateResponse with the form or redirect if event not found.
        """
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        context["active_nav"] = "cfp"
        context["form"] = ProposalCategoryForm()
        return TemplateResponse(self.request, "panel/cfp-create.html", context)

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        """Handle CFP category creation.

        Returns:
            Redirect response to CFP list on success, or form with errors.
        """
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        form = ProposalCategoryForm(self.request.POST)
        if not form.is_valid():
            context["active_nav"] = "cfp"
            context["form"] = form
            return TemplateResponse(self.request, "panel/cfp-create.html", context)

        name = form.cleaned_data["name"]
        category = self.request.di.uow.proposal_categories.create(
            current_event.pk, name
        )

        messages.success(self.request, _("Session type created successfully."))

        if self.request.POST.get("action") == "create_and_configure":
            return redirect(
                "panel:cfp-edit", event_slug=slug, category_slug=category.slug
            )
        return redirect("panel:cfp", slug=slug)


class CFPEditPageView(PanelAccessMixin, EventContextMixin, View):
    """Edit an existing CFP category."""

    request: PanelRequest

    def get(
        self, _request: PanelRequest, event_slug: str, category_slug: str
    ) -> HttpResponse:
        """Display the CFP category edit form.

        Returns:
            TemplateResponse with the form or redirect if not found.
        """
        context, current_event = self.get_event_context(event_slug)
        if current_event is None:
            return redirect("panel:index")

        try:
            category = self.request.di.uow.proposal_categories.read_by_slug(
                current_event.pk, category_slug
            )
        except NotFoundError:
            messages.error(self.request, _("Session type not found."))
            return redirect("panel:cfp", slug=event_slug)

        context["active_nav"] = "cfp"
        context["category"] = category
        context["form"] = ProposalCategoryForm(
            initial={
                "name": category.name,
                "description": category.description,
                "start_time": category.start_time,
                "end_time": category.end_time,
                "min_participants_limit": category.min_participants_limit,
                "max_participants_limit": category.max_participants_limit,
            }
        )

        # Get field requirements and order
        field_requirements = (
            self.request.di.uow.proposal_categories.get_field_requirements(category.pk)
        )
        field_order = self.request.di.uow.proposal_categories.get_field_order(
            category.pk
        )
        available_fields = list(
            self.request.di.uow.personal_data_fields.list_by_event(current_event.pk)
        )
        context["available_fields"] = sort_fields_by_order(
            available_fields, field_order
        )
        context["field_requirements"] = field_requirements
        context["field_order"] = field_order

        # Get session field requirements and order
        session_field_requirements = (
            self.request.di.uow.proposal_categories.get_session_field_requirements(
                category.pk
            )
        )
        session_field_order = (
            self.request.di.uow.proposal_categories.get_session_field_order(category.pk)
        )
        available_session_fields = list(
            self.request.di.uow.session_fields.list_by_event(current_event.pk)
        )
        context["available_session_fields"] = sort_fields_by_order(
            available_session_fields, session_field_order
        )
        context["session_field_requirements"] = session_field_requirements
        context["session_field_order"] = session_field_order

        # Get time slot requirements and order
        time_slot_requirements = (
            self.request.di.uow.proposal_categories.get_time_slot_requirements(
                category.pk
            )
        )
        time_slot_order = self.request.di.uow.proposal_categories.get_time_slot_order(
            category.pk
        )
        available_time_slots = list(
            self.request.di.uow.time_slots.list_by_event(current_event.pk)
        )
        context["available_time_slots"] = sort_fields_by_order(
            available_time_slots, time_slot_order
        )
        context["time_slot_requirements"] = time_slot_requirements
        context["time_slot_order"] = time_slot_order

        context["durations"] = category.durations
        context["proposal_count"] = self.request.di.uow.sessions.count_by_category(
            category.pk
        )
        return TemplateResponse(self.request, "panel/cfp-edit.html", context)

    def post(
        self, _request: PanelRequest, event_slug: str, category_slug: str
    ) -> HttpResponse:
        """Handle CFP category update.

        Returns:
            Redirect response to CFP list on success, or form with errors.
        """
        context, current_event = self.get_event_context(event_slug)
        if current_event is None:
            return redirect("panel:index")

        try:
            category = self.request.di.uow.proposal_categories.read_by_slug(
                current_event.pk, category_slug
            )
        except NotFoundError:
            messages.error(self.request, _("Session type not found."))
            return redirect("panel:cfp", slug=event_slug)

        form = ProposalCategoryForm(self.request.POST)
        if not form.is_valid():
            # Get field requirements and order
            field_requirements = (
                self.request.di.uow.proposal_categories.get_field_requirements(
                    category.pk
                )
            )
            field_order = self.request.di.uow.proposal_categories.get_field_order(
                category.pk
            )
            available_fields = list(
                self.request.di.uow.personal_data_fields.list_by_event(current_event.pk)
            )
            context["available_fields"] = sort_fields_by_order(
                available_fields, field_order
            )
            context["field_requirements"] = field_requirements
            context["field_order"] = field_order
            # Get session field requirements and order
            session_field_requirements = (
                self.request.di.uow.proposal_categories.get_session_field_requirements(
                    category.pk
                )
            )
            session_field_order = (
                self.request.di.uow.proposal_categories.get_session_field_order(
                    category.pk
                )
            )
            available_session_fields = list(
                self.request.di.uow.session_fields.list_by_event(current_event.pk)
            )
            context["available_session_fields"] = sort_fields_by_order(
                available_session_fields, session_field_order
            )
            context["session_field_requirements"] = session_field_requirements
            context["session_field_order"] = session_field_order
            # Get time slot requirements and order
            time_slot_requirements = (
                self.request.di.uow.proposal_categories.get_time_slot_requirements(
                    category.pk
                )
            )
            time_slot_order = (
                self.request.di.uow.proposal_categories.get_time_slot_order(category.pk)
            )
            available_time_slots = list(
                self.request.di.uow.time_slots.list_by_event(current_event.pk)
            )
            context["available_time_slots"] = sort_fields_by_order(
                available_time_slots, time_slot_order
            )
            context["time_slot_requirements"] = time_slot_requirements
            context["time_slot_order"] = time_slot_order
            context["durations"] = category.durations
            context["proposal_count"] = self.request.di.uow.sessions.count_by_category(
                category.pk
            )
            context["active_nav"] = "cfp"
            context["category"] = category
            context["form"] = form
            return TemplateResponse(self.request, "panel/cfp-edit.html", context)

        # Parse durations from POST (can be single value or list)
        durations_raw = self.request.POST.getlist("durations")
        durations: list[str] = [d for d in durations_raw if d]

        self.request.di.uow.proposal_categories.update(
            category.pk,
            {
                "name": form.cleaned_data["name"],
                "description": form.cleaned_data["description"],
                "start_time": form.cleaned_data["start_time"],
                "end_time": form.cleaned_data["end_time"],
                "durations": durations,
                "min_participants_limit": (
                    form.cleaned_data["min_participants_limit"] or 0
                ),
                "max_participants_limit": (
                    form.cleaned_data["max_participants_limit"] or 0
                ),
            },
        )

        # Parse and save field requirements with order (scoped to this event)
        field_requirements, field_order = scoped_requirements(
            self.request.POST,
            "field_",
            "field_order",
            self.request.di.uow.personal_data_fields.list_by_event(current_event.pk),
        )
        self.request.di.uow.proposal_categories.set_field_requirements(
            category.pk, field_requirements, field_order
        )

        # Parse and save session field requirements with order (scoped to this event)
        session_field_requirements, session_field_order = scoped_requirements(
            self.request.POST,
            "session_field_",
            "session_field_order",
            self.request.di.uow.session_fields.list_by_event(current_event.pk),
        )
        self.request.di.uow.proposal_categories.set_session_field_requirements(
            category.pk, session_field_requirements, session_field_order
        )

        # Parse and save time slot requirements with order (scoped to this event)
        time_slot_requirements, time_slot_order = scoped_requirements(
            self.request.POST,
            "time_slot_",
            "time_slot_order",
            self.request.di.uow.time_slots.list_by_event(current_event.pk),
        )
        self.request.di.uow.proposal_categories.set_time_slot_requirements(
            category.pk, time_slot_requirements, time_slot_order
        )

        messages.success(self.request, _("Session type updated successfully."))
        return redirect("panel:cfp", slug=event_slug)


class CFPDeleteActionView(PanelAccessMixin, EventContextMixin, View):
    """Delete a CFP category (POST only)."""

    request: PanelRequest
    http_method_names = ("post",)

    def post(
        self, _request: PanelRequest, event_slug: str, category_slug: str
    ) -> HttpResponse:
        """Handle CFP category deletion.

        Returns:
            Redirect response to CFP list.
        """
        _context, current_event = self.get_event_context(event_slug)
        if current_event is None:
            return redirect("panel:index")

        try:
            category = self.request.di.uow.proposal_categories.read_by_slug(
                current_event.pk, category_slug
            )
        except NotFoundError:
            messages.error(self.request, _("Session type not found."))
            return redirect("panel:cfp", slug=event_slug)

        service = PanelService(self.request.di.uow)
        if not service.delete_category(category.pk):
            messages.error(
                self.request, _("Cannot delete session type with existing proposals.")
            )
            return redirect("panel:cfp", slug=event_slug)

        messages.success(self.request, _("Session type deleted successfully."))
        return redirect("panel:cfp", slug=event_slug)
