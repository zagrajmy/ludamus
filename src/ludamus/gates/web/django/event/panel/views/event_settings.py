"""Event settings views: general, display, and proposal settings tabs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.timezone import localtime
from django.utils.translation import gettext as _
from django.utils.translation import pgettext
from django.views.generic.base import View

from ludamus.gates.web.django.event.panel.views.base import EventPanelMixin
from ludamus.gates.web.django.forms import EventSettingsForm, ProposalSettingsForm
from ludamus.gates.web.django.panel import PanelRequest, settings_tab_urls
from ludamus.gates.web.django.request_ids import parse_ids
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.event import (
    EventDatesInvalidError,
    EventPublicationInvalidError,
    EventSlugConflictError,
    EventUpdateData,
    EventVisibility,
)
from ludamus.pacts.images import StoredFile, resolve_uploaded_file_field, stored_file

if TYPE_CHECKING:
    from django import forms
    from django.http import HttpResponse

    from ludamus.pacts.event import EventDTO
    from ludamus.pacts.event_settings import ProposalSettingsUpdateData


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
        "address": cd.get("address") or "",
        "start_time": cd["start_time"],
        "end_time": cd["end_time"],
        "publication_time": cd.get("publication_time"),
        "visibility": EventVisibility(cd["visibility"]),
        "allow_facilitator_session_edit": _choice_to_override(
            cd.get("allow_facilitator_session_edit") or ""
        ),
        "auto_confirm_sessions": bool(cd.get("auto_confirm_sessions")),
        "use_session_cover_placeholders": bool(
            cd.get("use_session_cover_placeholders")
        ),
        "use_participants_label": bool(cd.get("use_participants_label")),
        "parley_enabled": _choice_to_override(cd.get("parley_enabled") or ""),
    }
    if (cover := resolve_uploaded_file_field(cd.get("cover_image"))) is not None:
        data["cover_image"] = cover
    if (logo := resolve_uploaded_file_field(cd.get("logo"))) is not None:
        data["logo"] = logo
    return data


def _stored_images(event: EventDTO) -> dict[str, StoredFile | None]:
    return {
        "cover_image": stored_file(
            event.cover_image_url, event.cover_image_original_name
        ),
        "logo": stored_file(event.logo_url, event.logo_original_name),
    }


def _follow_sphere_choices(
    form: EventSettingsForm, name: str, *, inherited: str, on: str, off: str
) -> None:
    # Null follows the sphere, which the first choice says the value of.
    field = cast("forms.ChoiceField", form.fields[name])
    field.choices = [
        ("", _("Use sphere default (currently: {})").format(inherited)),
        ("true", on),
        ("false", off),
    ]


class EventSettingsPageView(EventPanelMixin, View):
    """Event settings page view."""

    request: PanelRequest

    def _apply_facilitator_choices(self, form: EventSettingsForm) -> None:
        sphere = self.request.services.sphere_panel.read(
            self.request.context.current_sphere_id
        )
        _follow_sphere_choices(
            form,
            "allow_facilitator_session_edit",
            inherited=(
                _("allowed")
                if sphere.allow_facilitator_session_edit
                else _("disallowed")
            ),
            on=_("Allow"),
            off=_("Disallow"),
        )
        _follow_sphere_choices(
            form,
            "parley_enabled",
            inherited=(
                pgettext("event chat", "on")
                if sphere.parley_events_enabled
                else pgettext("event chat", "off")
            ),
            on=pgettext("event chat", "On"),
            off=pgettext("event chat", "Off"),
        )

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context = self.panel_context()

        context["active_nav"] = "settings"
        context["active_tab"] = "general"
        context["tab_urls"] = settings_tab_urls(slug)
        override = self.current_event.allow_facilitator_session_edit
        form = EventSettingsForm(
            initial={
                "name": self.current_event.name,
                "slug": self.current_event.slug,
                "description": self.current_event.description,
                "address": self.current_event.address,
                **_stored_images(self.current_event),
                "start_time": localtime(self.current_event.start_time),
                "end_time": localtime(self.current_event.end_time),
                "publication_time": (
                    localtime(self.current_event.publication_time)
                    if self.current_event.publication_time
                    else None
                ),
                "visibility": self.current_event.visibility.value,
                "allow_facilitator_session_edit": _override_to_choice(value=override),
                "auto_confirm_sessions": self.current_event.auto_confirm_sessions,
                "use_session_cover_placeholders": (
                    self.current_event.use_session_cover_placeholders
                ),
                "use_participants_label": self.current_event.use_participants_label,
                "parley_enabled": _override_to_choice(
                    value=self.current_event.parley_enabled
                ),
            }
        )
        self._apply_facilitator_choices(form)
        context["form"] = form
        return TemplateResponse(self.request, "panel/settings.html", context)

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context = self.panel_context()

        form = EventSettingsForm(
            self.request.POST,
            self.request.FILES,
            initial=_stored_images(self.current_event),
        )
        if not form.is_valid():
            return self._render_with_form(context=context, slug=slug, form=form)

        cd = form.cleaned_data
        new_slug = cd["slug"]

        try:
            self.request.services.event_settings.update_general(
                sphere_id=self.request.context.current_sphere_id,
                slug=slug,
                data=_event_update_data(cd, new_slug),
            )
        except EventSlugConflictError:
            form.add_error("slug", _("An event with this slug already exists."))
            return self._render_with_form(context=context, slug=slug, form=form)
        except EventDatesInvalidError:
            form.add_error("end_time", _("End time must be after start time."))
            return self._render_with_form(context=context, slug=slug, form=form)
        except EventPublicationInvalidError:
            form.add_error(
                "publication_time", _("Publication time must not be after start time.")
            )
            return self._render_with_form(context=context, slug=slug, form=form)
        except NotFoundError:
            messages.error(self.request, _("Event not found."))
            return redirect("panel:index")

        messages.success(self.request, _("Event settings saved successfully."))
        return redirect("panel:event-settings", slug=new_slug)

    def _render_with_form(
        self, *, context: dict[str, object], slug: str, form: EventSettingsForm
    ) -> HttpResponse:
        context["active_nav"] = "settings"
        context["active_tab"] = "general"
        context["tab_urls"] = settings_tab_urls(slug)
        self._apply_facilitator_choices(form)
        context["form"] = form
        return TemplateResponse(self.request, "panel/settings.html", context)


class EventDisplaySettingsPageView(EventPanelMixin, View):
    """Display settings page — displayed session fields on cards."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context = self.panel_context()

        context["active_nav"] = "settings"
        context["active_tab"] = "display"
        context["tab_urls"] = settings_tab_urls(slug)

        display = self.request.services.event_settings.get_display_context(
            sphere_id=self.request.context.current_sphere_id, slug=slug
        )
        context["fields"] = display.fields
        context["shown_on_cards_ids"] = display.shown_on_cards_ids
        context["has_any_fields"] = display.has_any_fields

        return TemplateResponse(self.request, "panel/display-settings.html", context)

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        raw_ids = self.request.POST.getlist("show_on_cards")
        if len(selected_ids := parse_ids(raw_ids)) != len(raw_ids):
            messages.error(self.request, _("Invalid field selection."))
            return redirect("panel:event-display-settings", slug=slug)

        try:
            self.request.services.event_settings.update_shown_on_cards(
                sphere_id=self.request.context.current_sphere_id,
                slug=slug,
                selected_ids=selected_ids,
            )
        except NotFoundError:
            messages.error(self.request, _("Event not found."))
            return redirect("panel:index")

        messages.success(self.request, _("Display settings saved successfully."))
        return redirect("panel:event-display-settings", slug=slug)


class EventProposalSettingsPageView(EventPanelMixin, View):
    """Proposal settings page — description, dates, apply-to-categories."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context = self.panel_context()

        context["active_nav"] = "settings"
        context["active_tab"] = "proposals"
        context["tab_urls"] = settings_tab_urls(slug)
        proposal_settings = self.request.services.event_settings.get_proposal_settings(
            sphere_id=self.request.context.current_sphere_id, slug=slug
        )
        context["form"] = ProposalSettingsForm(
            initial={
                "proposal_description": proposal_settings.description,
                "proposal_start_time": (
                    localtime(self.current_event.proposal_start_time)
                    if self.current_event.proposal_start_time
                    else None
                ),
                "proposal_end_time": (
                    localtime(self.current_event.proposal_end_time)
                    if self.current_event.proposal_end_time
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


class EventIntegrationSettingsPageView(EventPanelMixin, View):
    """Integrations tab — flat CRUD list across all kinds."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context = self.panel_context()

        context["active_nav"] = "settings"
        context["active_tab"] = "integrations"
        context["tab_urls"] = settings_tab_urls(slug)
        context["integrations"] = (
            self.request.services.event_integrations.list_for_event(
                self.current_event.pk
            )
        )
        return TemplateResponse(
            self.request, "panel/integration-settings.html", context
        )
