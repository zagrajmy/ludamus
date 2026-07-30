"""Event settings views: general, display, and proposal settings tabs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django import forms
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
)
from ludamus.gates.web.django.forms import EventSettingsForm, ProposalSettingsForm
from ludamus.gates.web.django.panel import settings_tab_urls
from ludamus.pacts import EventUpdateData, NotFoundError
from ludamus.pacts.event_settings import EventSlugTakenError, ProposalSettingsUpdateData
from ludamus.pacts.legacy import resolve_uploaded_file_field

if TYPE_CHECKING:
    from django.http import HttpResponse


def _override_to_choice(*, value: bool | None) -> str:
    if value is None:
        return ""
    return "true" if value else "false"


def _choice_to_override(value: str) -> bool | None:
    if value == "true":
        return True
    if value == "false":
        return False
    return None


def _event_update_data(cd: dict[str, Any], slug: str) -> EventUpdateData:
    data: EventUpdateData = {
        "name": cd["name"],
        "slug": slug,
        "description": cd.get("description") or "",
        "start_time": cd["start_time"],
        "end_time": cd["end_time"],
        "publication_time": cd.get("publication_time"),
        "allow_facilitator_session_edit": _choice_to_override(
            cd.get("allow_facilitator_session_edit") or ""
        ),
        "auto_confirm_sessions": bool(cd.get("auto_confirm_sessions")),
        "use_session_cover_placeholders": bool(
            cd.get("use_session_cover_placeholders")
        ),
        "use_participants_label": bool(cd.get("use_participants_label")),
    }
    if (cover := resolve_uploaded_file_field(cd.get("cover_image"))) is not None:
        data["cover_image"] = cover
    if (logo := resolve_uploaded_file_field(cd.get("logo"))) is not None:
        data["logo"] = logo
    return data


class EventSettingsPageView(PanelAccessMixin, EventContextMixin, View):
    """Event settings page view."""

    request: PanelRequest

    def _apply_facilitator_choices(self, form: EventSettingsForm) -> None:
        sphere = self.request.services.sphere_panel.read(
            self.request.context.current_sphere_id
        )
        resolved = (
            _("allowed") if sphere.allow_facilitator_session_edit else _("disallowed")
        )
        edit_field = form.fields["allow_facilitator_session_edit"]
        if isinstance(edit_field, forms.ChoiceField):
            edit_field.choices = [
                ("", _("Use sphere default (currently: {})").format(resolved)),
                ("true", _("Allow")),
                ("false", _("Disallow")),
            ]

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        context["active_nav"] = "settings"
        context["active_tab"] = "general"
        context["tab_urls"] = settings_tab_urls(slug)
        override = current_event.allow_facilitator_session_edit
        form = EventSettingsForm(
            initial={
                "name": current_event.name,
                "slug": current_event.slug,
                "description": current_event.description,
                "cover_image": current_event.cover_image_url or None,
                "logo": current_event.logo_url or None,
                "start_time": localtime(current_event.start_time),
                "end_time": localtime(current_event.end_time),
                "publication_time": (
                    localtime(current_event.publication_time)
                    if current_event.publication_time
                    else None
                ),
                "allow_facilitator_session_edit": _override_to_choice(value=override),
                "auto_confirm_sessions": current_event.auto_confirm_sessions,
                "use_session_cover_placeholders": (
                    current_event.use_session_cover_placeholders
                ),
                "use_participants_label": current_event.use_participants_label,
            }
        )
        self._apply_facilitator_choices(form)
        context["form"] = form
        return TemplateResponse(self.request, "panel/settings.html", context)

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        if self.get_current_event(slug) is None:
            return redirect("panel:index")

        form = EventSettingsForm(self.request.POST, self.request.FILES)
        if not form.is_valid():
            return self._render_with_form(slug, form)

        cd = form.cleaned_data
        new_slug = cd["slug"]

        try:
            self.request.services.event_settings.update_general(
                sphere_id=self.request.context.current_sphere_id,
                slug=slug,
                data=_event_update_data(cd, new_slug),
            )
        except EventSlugTakenError:
            messages.error(self.request, _("An event with this slug already exists."))
            return redirect("panel:event-settings", slug=slug)
        except NotFoundError:
            messages.error(self.request, _("Event not found."))
            return redirect("panel:event-settings", slug=slug)

        messages.success(self.request, _("Event settings saved successfully."))
        return redirect("panel:event-settings", slug=new_slug)

    def _render_with_form(self, slug: str, form: EventSettingsForm) -> HttpResponse:
        context, _current_event = self.get_event_context(slug)
        context["active_nav"] = "settings"
        context["active_tab"] = "general"
        context["tab_urls"] = settings_tab_urls(slug)
        self._apply_facilitator_choices(form)
        context["form"] = form
        return TemplateResponse(self.request, "panel/settings.html", context)


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

        display = self.request.services.event_settings.get_display_context(
            current_event.pk
        )
        context["fields"] = display.fields
        context["filterable_field_ids"] = display.displayed_field_ids

        return TemplateResponse(self.request, "panel/display-settings.html", context)

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        selected_ids = [
            int(pk) for pk in self.request.POST.getlist("displayed_session_fields")
        ]

        try:
            self.request.services.event_settings.update_displayed_fields(
                sphere_id=self.request.context.current_sphere_id,
                slug=slug,
                selected_ids=selected_ids,
            )
        except NotFoundError:
            messages.error(self.request, _("Event not found."))
            return redirect("panel:index")

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
        proposal_settings = self.request.services.event_settings.get_proposal_settings(
            current_event.pk
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
                "allow_anonymous_proposals": (
                    proposal_settings.allow_anonymous_proposals
                ),
            }
        )
        return TemplateResponse(self.request, "panel/proposal-settings.html", context)

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        form = ProposalSettingsForm(self.request.POST)
        if not form.is_valid():
            for field_errors in form.errors.values():
                messages.error(self.request, str(field_errors[0]))
            return redirect("panel:event-proposal-settings", slug=slug)

        cd = form.cleaned_data
        data: ProposalSettingsUpdateData = {
            "description": cd.get("proposal_description") or "",
            "proposal_start_time": cd.get("proposal_start_time"),
            "proposal_end_time": cd.get("proposal_end_time"),
            "allow_anonymous_proposals": bool(cd.get("allow_anonymous_proposals")),
            "apply_dates_to_categories": bool(cd.get("apply_dates_to_categories")),
        }

        try:
            self.request.services.event_settings.update_proposal_settings(
                sphere_id=self.request.context.current_sphere_id, slug=slug, data=data
            )
        except NotFoundError:
            messages.error(self.request, _("Event not found."))
            return redirect("panel:index")

        messages.success(self.request, _("Proposal settings saved successfully."))
        return redirect("panel:event-proposal-settings", slug=slug)


class EventIntegrationSettingsPageView(PanelAccessMixin, EventContextMixin, View):
    """Integrations tab — flat CRUD list across all kinds."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        context["active_nav"] = "settings"
        context["active_tab"] = "integrations"
        context["tab_urls"] = settings_tab_urls(slug)
        context["integrations"] = (
            self.request.services.event_integrations.list_for_event(current_event.pk)
        )
        return TemplateResponse(
            self.request, "panel/integration-settings.html", context
        )
