"""Event settings views: general, display, and proposal settings tabs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.timezone import localtime
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.chronology.panel.views.base import (
    EventContextMixin,
    PanelAccessMixin,
    PanelRequest,
    settings_tab_urls,
)
from ludamus.gates.web.django.forms import EventSettingsForm, ProposalSettingsForm
from ludamus.pacts import EventUpdateData, NotFoundError

if TYPE_CHECKING:
    from django.http import HttpResponse


class EventSettingsPageView(PanelAccessMixin, EventContextMixin, View):
    """Event settings page view."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        context["active_nav"] = "settings"
        context["active_tab"] = "general"
        context["tab_urls"] = settings_tab_urls(slug)
        context["form"] = EventSettingsForm(
            initial={
                "name": current_event.name,
                "slug": current_event.slug,
                "description": current_event.description,
                "start_time": localtime(current_event.start_time),
                "end_time": localtime(current_event.end_time),
                "publication_time": (
                    localtime(current_event.publication_time)
                    if current_event.publication_time
                    else None
                ),
            }
        )
        return TemplateResponse(self.request, "panel/settings.html", context)

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        sphere_id = self.request.context.current_sphere_id

        try:
            current_event = self.request.di.uow.events.read_by_slug(slug, sphere_id)
        except NotFoundError:
            messages.error(self.request, _("Event not found."))
            return redirect("panel:index")

        form = EventSettingsForm(self.request.POST)
        if not form.is_valid():
            for field_errors in form.errors.values():
                messages.error(self.request, str(field_errors[0]))
            return redirect("panel:event-settings", slug=slug)

        cd = form.cleaned_data

        # Check slug uniqueness if changed
        if (new_slug := cd["slug"]) != current_event.slug:
            try:
                self.request.di.uow.events.read_by_slug(new_slug, sphere_id)
                messages.error(
                    self.request, _("An event with this slug already exists.")
                )
                return redirect("panel:event-settings", slug=slug)
            except NotFoundError:
                pass  # Slug is available

        data: EventUpdateData = {
            "name": cd["name"],
            "slug": new_slug,
            "description": cd.get("description") or "",
            "start_time": cd["start_time"],
            "end_time": cd["end_time"],
            "publication_time": cd.get("publication_time"),
        }

        try:
            self.request.di.uow.events.update(current_event.pk, data)
        except NotFoundError:
            messages.error(self.request, _("Event not found."))
            return redirect("panel:event-settings", slug=slug)

        messages.success(self.request, _("Event settings saved successfully."))
        return redirect("panel:event-settings", slug=new_slug)


class EventDisplaySettingsPageView(PanelAccessMixin, EventContextMixin, View):
    """Display settings page — displayed session fields on cards."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        context["active_nav"] = "settings"
        context["active_tab"] = "display"
        context["tab_urls"] = settings_tab_urls(slug)

        all_fields = self.request.di.uow.session_fields.list_by_event(current_event.pk)
        settings_dto = self.request.di.uow.event_settings.read_or_create(
            current_event.pk
        )
        context["fields"] = [f for f in all_fields if f.is_public]
        context["filterable_field_ids"] = settings_dto.displayed_session_field_ids

        return TemplateResponse(self.request, "panel/display-settings.html", context)

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        sphere_id = self.request.context.current_sphere_id

        try:
            current_event = self.request.di.uow.events.read_by_slug(slug, sphere_id)
        except NotFoundError:
            messages.error(self.request, _("Event not found."))
            return redirect("panel:index")

        selected_ids = [
            int(pk) for pk in self.request.POST.getlist("displayed_session_fields")
        ]
        # Validate against public session field PKs only
        valid_pks = {
            f.pk
            for f in self.request.di.uow.session_fields.list_by_event(current_event.pk)
            if f.is_public
        }
        filtered_ids = [pk for pk in selected_ids if pk in valid_pks]

        self.request.di.uow.event_settings.update_displayed_fields(
            current_event.pk, filtered_ids
        )

        messages.success(self.request, _("Display settings saved successfully."))
        return redirect("panel:event-display-settings", slug=slug)


class EventProposalSettingsPageView(PanelAccessMixin, EventContextMixin, View):
    """Proposal settings page — description, dates, apply-to-categories."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        context["active_nav"] = "settings"
        context["active_tab"] = "proposals"
        context["tab_urls"] = settings_tab_urls(slug)
        proposal_settings = (
            self.request.di.uow.event_proposal_settings.read_or_create_by_event(
                current_event.pk
            )
        )
        context["form"] = ProposalSettingsForm(
            initial={
                "proposal_description": proposal_settings.description,
                "proposal_start_time": (
                    localtime(current_event.proposal_start_time)
                    if current_event.proposal_start_time
                    else None
                ),
                "proposal_end_time": (
                    localtime(current_event.proposal_end_time)
                    if current_event.proposal_end_time
                    else None
                ),
            }
        )
        return TemplateResponse(self.request, "panel/proposal-settings.html", context)

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        sphere_id = self.request.context.current_sphere_id

        try:
            current_event = self.request.di.uow.events.read_by_slug(slug, sphere_id)
        except NotFoundError:
            messages.error(self.request, _("Event not found."))
            return redirect("panel:index")

        form = ProposalSettingsForm(self.request.POST)
        if not form.is_valid():
            for field_errors in form.errors.values():
                messages.error(self.request, str(field_errors[0]))
            return redirect("panel:event-proposal-settings", slug=slug)

        cd = form.cleaned_data

        with self.request.di.uow.atomic():
            # Save proposal description
            self.request.di.uow.event_proposal_settings.update_description(
                current_event.pk, cd.get("proposal_description") or ""
            )

            # Save proposal dates
            data: EventUpdateData = {
                "proposal_start_time": cd.get("proposal_start_time"),
                "proposal_end_time": cd.get("proposal_end_time"),
            }
            self.request.di.uow.events.update(current_event.pk, data)

            # Optionally apply dates to all categories
            if cd.get("apply_dates_to_categories"):
                categories = self.request.di.uow.proposal_categories.list_by_event(
                    current_event.pk
                )
                for category in categories:
                    self.request.di.uow.proposal_categories.update(
                        category.pk,
                        {
                            "start_time": cd.get("proposal_start_time"),
                            "end_time": cd.get("proposal_end_time"),
                        },
                    )

        messages.success(self.request, _("Proposal settings saved successfully."))
        return redirect("panel:event-proposal-settings", slug=slug)
