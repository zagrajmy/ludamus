from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
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

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.pacts import EventDTO

_SETTINGS_URL = "panel:event-enrollment-settings"


def _window_data(form: EnrollmentWindowForm) -> EnrollmentWindowData:
    return EnrollmentWindowData.model_validate(form.cleaned_data)


def _window_initial(window: EnrollmentWindowDTO) -> dict[str, object]:
    return {
        **window.model_dump(),
        "start_time": localtime(window.start_time),
        "end_time": localtime(window.end_time),
    }


class EnrollmentSettingsViewMixin(EventContextMixin):
    request: EventPanelRequest

    def tab_context(self, slug: str) -> tuple[dict[str, object], EventDTO] | None:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return None
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
        if (seeded := self.tab_context(slug)) is None:
            return redirect("panel:index")
        context, _current_event = seeded
        context.update(form=form, window=window)
        return TemplateResponse(
            self.request, "panel/enrollment-window-form.html", context
        )

    def window_not_found(self, slug: str) -> HttpResponse:
        messages.error(self.request, _("Enrollment window not found."))
        return redirect(_SETTINGS_URL, slug=slug)


class EventEnrollmentSettingsPageView(
    EventPanelAccessMixin, EnrollmentSettingsViewMixin, View
):
    request: EventPanelRequest

    def get(self, _request: EventPanelRequest, slug: str) -> HttpResponse:
        if (seeded := self.tab_context(slug)) is None:
            return redirect("panel:index")
        context, current_event = seeded
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

        if (current_event := self.get_current_event(slug)) is None:
            return redirect("panel:index")
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
        if (current_event := self.get_current_event(slug)) is None:
            return redirect("panel:index")
        window = self.request.services.enrollment_settings.read_window(
            current_event.pk, pk
        )
        if window is None:
            return self.window_not_found(slug)
        return self.render_window_form(
            slug=slug,
            form=EnrollmentWindowForm(initial=_window_initial(window)),
            window=window,
        )

    def post(self, _request: EventPanelRequest, slug: str, pk: int) -> HttpResponse:
        if (current_event := self.get_current_event(slug)) is None:
            return redirect("panel:index")
        window = self.request.services.enrollment_settings.read_window(
            current_event.pk, pk
        )
        if window is None:
            return self.window_not_found(slug)

        form = EnrollmentWindowForm(self.request.POST)
        if not form.is_valid():
            return self.render_window_form(slug=slug, form=form, window=window)
        updated = self.request.services.enrollment_settings.update_window(
            event_id=current_event.pk, pk=pk, data=_window_data(form)
        )
        if updated is None:
            return self.window_not_found(slug)
        messages.success(self.request, _("Enrollment window saved."))
        return redirect(_SETTINGS_URL, slug=slug)


class EnrollmentWindowDeleteActionView(
    EventPanelAccessMixin, EnrollmentSettingsViewMixin, View
):
    request: EventPanelRequest
    http_method_names = ("post",)

    def post(self, _request: EventPanelRequest, slug: str, pk: int) -> HttpResponse:
        if (current_event := self.get_current_event(slug)) is None:
            return redirect("panel:index")
        if not self.request.services.enrollment_settings.delete_window(
            current_event.pk, pk
        ):
            return self.window_not_found(slug)
        messages.success(self.request, _("Enrollment window deleted."))
        return redirect(_SETTINGS_URL, slug=slug)
