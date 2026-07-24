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
    settings_tab_urls,
)
from ludamus.pacts.enrollment import EnrollmentWindowData, EnrollmentWindowDTO

if TYPE_CHECKING:
    from django.http import HttpResponse


def _window_data(form: EnrollmentWindowForm) -> EnrollmentWindowData:
    return EnrollmentWindowData.model_validate(form.cleaned_data)


def _window_initial(window: EnrollmentWindowDTO) -> dict[str, object]:
    return {
        **window.model_dump(),
        "start_time": localtime(window.start_time),
        "end_time": localtime(window.end_time),
    }


class EventEnrollmentSettingsPageView(EventPanelAccessMixin, EventContextMixin, View):
    request: EventPanelRequest

    def get(self, _request: EventPanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        context.update(
            active_nav="settings",
            active_tab="enrollment",
            tab_urls=settings_tab_urls(slug),
            windows=self.request.services.enrollment_settings.list_windows(
                current_event.pk
            ),
            now=now(),
        )
        return TemplateResponse(self.request, "panel/enrollment-settings.html", context)


class EnrollmentWindowCreatePageView(EventPanelAccessMixin, EventContextMixin, View):
    request: EventPanelRequest

    def get(self, _request: EventPanelRequest, slug: str) -> HttpResponse:
        return self._render(slug, EnrollmentWindowForm())

    def post(self, _request: EventPanelRequest, slug: str) -> HttpResponse:
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


class EnrollmentWindowEditPageView(EventPanelAccessMixin, EventContextMixin, View):
    request: EventPanelRequest

    def get(self, _request: EventPanelRequest, slug: str, pk: int) -> HttpResponse:
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

    def post(self, _request: EventPanelRequest, slug: str, pk: int) -> HttpResponse:
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


class EnrollmentWindowDeleteActionView(EventPanelAccessMixin, EventContextMixin, View):
    request: EventPanelRequest
    http_method_names = ("post",)

    def post(self, _request: EventPanelRequest, slug: str, pk: int) -> HttpResponse:
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
