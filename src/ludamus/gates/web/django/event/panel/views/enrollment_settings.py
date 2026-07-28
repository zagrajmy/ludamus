from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.timezone import localtime, now
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.event.panel.forms import EnrollmentWindowForm
from ludamus.gates.web.django.event.panel.views.base import (
    EventContextMixin,
    EventPanelAccessMixin,
    EventPanelRequest,
)
from ludamus.gates.web.django.panel import settings_tab_urls
from ludamus.pacts.enrollment import EnrollmentWindowData, EnrollmentWindowDTO
from ludamus.pacts.legacy import RedirectError

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.pacts import EventDTO

_SETTINGS_URL = "panel:event-enrollment-settings"


def _settings_url(slug: str) -> str:
    return reverse(_SETTINGS_URL, kwargs={"slug": slug})


def _window_not_found(slug: str) -> RedirectError:
    return RedirectError(_settings_url(slug), error=_("Enrollment window not found."))


def _window_data(form: EnrollmentWindowForm) -> EnrollmentWindowData:
    cleaned = form.cleaned_data
    return EnrollmentWindowData(
        start_time=cleaned["start_time"],
        end_time=cleaned["end_time"],
        percentage_slots=cleaned["percentage_slots"],
        max_waitlist_sessions=cleaned["max_waitlist_sessions"],
        limit_to_end_time=cleaned["limit_to_end_time"],
        restrict_to_configured_users=cleaned["restrict_to_configured_users"],
        allow_anonymous_enrollment=cleaned["allow_anonymous_enrollment"],
        banner_text=cleaned["banner_text"],
    )


def _window_initial(window: EnrollmentWindowDTO) -> dict[str, object]:
    return {
        **window.model_dump(),
        "start_time": localtime(window.start_time),
        "end_time": localtime(window.end_time),
    }


class EnrollmentSettingsViewMixin(EventContextMixin):
    request: EventPanelRequest

    def tab_context(self, slug: str) -> tuple[dict[str, object], EventDTO]:
        context, current_event = self.require_event_context(slug)
        context.update(
            active_nav="settings",
            active_tab="enrollment",
            tab_urls=settings_tab_urls(slug),
        )
        return context, current_event

    def render_window_form(
        self,
        *,
        slug: str,
        form: EnrollmentWindowForm,
        window: EnrollmentWindowDTO | None,
    ) -> HttpResponse:
        context, _current_event = self.tab_context(slug)
        context.update(form=form, window=window)
        return TemplateResponse(
            self.request, "panel/enrollment-window-form.html", context
        )


class EventEnrollmentSettingsPageView(
    EventPanelAccessMixin, EnrollmentSettingsViewMixin, View
):
    request: EventPanelRequest

    def get(self, _request: EventPanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.tab_context(slug)
        context.update(
            windows=self.request.services.enrollment_settings.list_windows(
                current_event.pk
            ),
            now=now(),
        )
        return TemplateResponse(self.request, "panel/enrollment-settings.html", context)


class EnrollmentWindowCreatePageView(
    EventPanelAccessMixin, EnrollmentSettingsViewMixin, View
):
    request: EventPanelRequest

    def get(self, _request: EventPanelRequest, slug: str) -> HttpResponse:
        return self.render_window_form(
            slug=slug, form=EnrollmentWindowForm(), window=None
        )

    def post(self, _request: EventPanelRequest, slug: str) -> HttpResponse:
        form = EnrollmentWindowForm(self.request.POST)
        if not form.is_valid():
            return self.render_window_form(slug=slug, form=form, window=None)

        current_event = self.require_current_event(slug)
        self.request.services.enrollment_settings.create_window(
            current_event.pk, _window_data(form)
        )
        messages.success(self.request, _("Enrollment window created."))
        return redirect(_SETTINGS_URL, slug=slug)


class EnrollmentWindowEditPageView(
    EventPanelAccessMixin, EnrollmentSettingsViewMixin, View
):
    request: EventPanelRequest

    def get(self, _request: EventPanelRequest, slug: str, pk: int) -> HttpResponse:
        window = self._read_window(slug, pk)
        return self.render_window_form(
            slug=slug,
            form=EnrollmentWindowForm(initial=_window_initial(window)),
            window=window,
        )

    def post(self, _request: EventPanelRequest, slug: str, pk: int) -> HttpResponse:
        window = self._read_window(slug, pk)
        form = EnrollmentWindowForm(self.request.POST)
        if not form.is_valid():
            return self.render_window_form(slug=slug, form=form, window=window)

        updated = self.request.services.enrollment_settings.update_window(
            event_id=window.event_id, pk=pk, data=_window_data(form)
        )
        if updated is None:
            raise _window_not_found(slug)
        messages.success(self.request, _("Enrollment window saved."))
        return redirect(_SETTINGS_URL, slug=slug)

    def _read_window(self, slug: str, pk: int) -> EnrollmentWindowDTO:
        current_event = self.require_current_event(slug)
        window = self.request.services.enrollment_settings.read_window(
            current_event.pk, pk
        )
        if window is None:
            raise _window_not_found(slug)
        return window


class EnrollmentWindowDeleteActionView(
    EventPanelAccessMixin, EnrollmentSettingsViewMixin, View
):
    request: EventPanelRequest
    http_method_names = ("post",)

    def post(self, _request: EventPanelRequest, slug: str, pk: int) -> HttpResponse:
        current_event = self.require_current_event(slug)
        if not self.request.services.enrollment_settings.delete_window(
            current_event.pk, pk
        ):
            raise _window_not_found(slug)
        messages.success(self.request, _("Enrollment window deleted."))
        return redirect(_SETTINGS_URL, slug=slug)
