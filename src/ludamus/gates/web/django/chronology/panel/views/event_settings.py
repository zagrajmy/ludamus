"""Event settings views: general, display, and proposal settings tabs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django import forms
from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.timezone import localtime, now
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.chronology.panel.views.base import (
    EventContextMixin,
    PanelAccessMixin,
    PanelRequest,
    settings_tab_urls,
)
from ludamus.gates.web.django.forms import (
    EnrollmentWindowForm,
    EventSettingsForm,
    ProposalSettingsForm,
)
from ludamus.pacts import EventUpdateData, NotFoundError
from ludamus.pacts.enrollment import EnrollmentWindowData, EnrollmentWindowDTO
from ludamus.pacts.legacy import resolve_cover_image

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
    if (cover := resolve_cover_image(cd.get("cover_image"))) is not None:
        data["cover_image"] = cover
    # Only overwrite the logo when a new file was uploaded, so saving the
    # settings form without re-picking a file keeps the existing logo.
    if cd.get("logo"):
        data["logo"] = cd["logo"]
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
        sphere_id = self.request.context.current_sphere_id

        try:
            current_event = self.request.di.uow.events.read_by_slug(slug, sphere_id)
        except NotFoundError:
            messages.error(self.request, _("Event not found."))
            return redirect("panel:index")

        form = EventSettingsForm(self.request.POST, self.request.FILES)
        if not form.is_valid():
            return self._render_with_form(slug, form)

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

        data = _event_update_data(cd, new_slug)

        try:
            self.request.di.uow.events.update(current_event.pk, data)
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
                "allow_anonymous_proposals": (
                    proposal_settings.allow_anonymous_proposals
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

            self.request.di.uow.event_proposal_settings.update_allow_anonymous_proposals(
                current_event.pk, allow=bool(cd.get("allow_anonymous_proposals"))
            )

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


def _window_data(form: EnrollmentWindowForm) -> EnrollmentWindowData:
    cleaned = form.cleaned_data
    return EnrollmentWindowData(
        start_time=cleaned["start_time"],
        end_time=cleaned["end_time"],
        percentage_slots=cleaned["percentage_slots"],
        limit_to_end_time=bool(cleaned.get("limit_to_end_time")),
        banner_text=cleaned.get("banner_text") or "",
        max_waitlist_sessions=cleaned["max_waitlist_sessions"],
        restrict_to_configured_users=bool(cleaned.get("restrict_to_configured_users")),
        allow_anonymous_enrollment=bool(cleaned.get("allow_anonymous_enrollment")),
    )


def _window_initial(window: EnrollmentWindowDTO) -> dict[str, object]:
    return {
        **window.model_dump(),
        "start_time": localtime(window.start_time),
        "end_time": localtime(window.end_time),
    }


class EventEnrollmentSettingsPageView(PanelAccessMixin, EventContextMixin, View):
    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        context["active_nav"] = "settings"
        context["active_tab"] = "enrollment"
        context["tab_urls"] = settings_tab_urls(slug)
        context["windows"] = self.request.services.enrollment_settings.list_windows(
            current_event.pk
        )
        context["now"] = now()
        return TemplateResponse(self.request, "panel/enrollment-settings.html", context)


class EnrollmentWindowCreatePageView(PanelAccessMixin, EventContextMixin, View):
    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        return self._render(slug, EnrollmentWindowForm())

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        form = EnrollmentWindowForm(self.request.POST)
        if not form.is_valid():
            return self._render(slug, form)

        if (current_event := self.get_current_event(slug)) is None:
            return redirect("panel:index")
        self.request.services.enrollment_settings.create_window(
            current_event.pk, _window_data(form)
        )
        messages.success(self.request, _("Enrollment window created."))
        return redirect("panel:event-enrollment-settings", slug=slug)

    def _render(self, slug: str, form: EnrollmentWindowForm) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")
        context.update(
            active_nav="settings",
            active_tab="enrollment",
            tab_urls=settings_tab_urls(slug),
            form=form,
            window=None,
        )
        return TemplateResponse(
            self.request, "panel/enrollment-window-form.html", context
        )


class EnrollmentWindowEditPageView(PanelAccessMixin, EventContextMixin, View):
    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
        if (current_event := self.get_current_event(slug)) is None:
            return redirect("panel:index")
        window = self.request.services.enrollment_settings.read_window(
            current_event.pk, pk
        )
        if window is None:
            messages.error(self.request, _("Enrollment window not found."))
            return redirect("panel:event-enrollment-settings", slug=slug)
        return self._render(
            slug=slug,
            window=window,
            form=EnrollmentWindowForm(initial=_window_initial(window)),
        )

    def post(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
        if (current_event := self.get_current_event(slug)) is None:
            return redirect("panel:index")
        window = self.request.services.enrollment_settings.read_window(
            current_event.pk, pk
        )
        if window is None:
            messages.error(self.request, _("Enrollment window not found."))
            return redirect("panel:event-enrollment-settings", slug=slug)

        form = EnrollmentWindowForm(self.request.POST)
        if not form.is_valid():
            return self._render(slug=slug, window=window, form=form)
        updated = self.request.services.enrollment_settings.update_window(
            event_id=current_event.pk, pk=pk, data=_window_data(form)
        )
        if updated is None:
            messages.error(self.request, _("Enrollment window not found."))
        else:
            messages.success(self.request, _("Enrollment window saved."))
        return redirect("panel:event-enrollment-settings", slug=slug)

    def _render(
        self, *, slug: str, window: EnrollmentWindowDTO, form: EnrollmentWindowForm
    ) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")
        context.update(
            active_nav="settings",
            active_tab="enrollment",
            tab_urls=settings_tab_urls(slug),
            form=form,
            window=window,
        )
        return TemplateResponse(
            self.request, "panel/enrollment-window-form.html", context
        )


class EnrollmentWindowDeleteActionView(PanelAccessMixin, EventContextMixin, View):
    request: PanelRequest
    http_method_names = ("post",)

    def post(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
        if (current_event := self.get_current_event(slug)) is None:
            return redirect("panel:index")
        deleted = self.request.services.enrollment_settings.delete_window(
            current_event.pk, pk
        )
        if deleted:
            messages.success(self.request, _("Enrollment window deleted."))
        else:
            messages.error(self.request, _("Enrollment window not found."))
        return redirect("panel:event-enrollment-settings", slug=slug)


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
