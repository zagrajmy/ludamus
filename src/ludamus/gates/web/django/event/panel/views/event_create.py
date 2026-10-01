from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.event.panel.forms import event_create_form
from ludamus.gates.web.django.event.panel.views.base import (
    EventPanelAccessMixin,
    EventPanelRequest,
)
from ludamus.pacts.event import (
    EventCreateData,
    EventDatesInvalidError,
    EventSlugConflictError,
)
from ludamus.pacts.legacy import NotFoundError

if TYPE_CHECKING:
    from django import forms
    from django.http import HttpResponse

    from ludamus.pacts.legacy import EventDTO


class EventCreatePageView(EventPanelAccessMixin, View):
    request: EventPanelRequest

    def get(self, _request: EventPanelRequest) -> HttpResponse:
        events = self._events()
        return self._render(event_create_form(events)(), events=events)

    def post(self, _request: EventPanelRequest) -> HttpResponse:
        events = self._events()
        form = event_create_form(events)(self.request.POST)
        if not form.is_valid():
            return self._render(form, events=events)
        data = form.cleaned_data
        try:
            event = self.request.services.events.create(
                sphere_id=self.request.context.current_sphere_id,
                data=EventCreateData(
                    name=data["name"],
                    slug=data["slug"],
                    description="",
                    start_time=data["start_time"],
                    end_time=data["end_time"],
                    publication_time=None,
                    auto_confirm_sessions=False,
                ),
                based_on_id=data.get("based_on"),
            )
        except EventSlugConflictError:
            form.add_error("slug", _("Another event in this sphere uses this slug."))
            return self._render(form, events=events)
        except EventDatesInvalidError:
            form.add_error("end_time", _("End time must be after start time."))
            return self._render(form, events=events)
        except NotFoundError:
            form.add_error("based_on", _("Pick an event from this sphere."))
            return self._render(form, events=events)
        messages.success(
            self.request,
            _("Created %(name)s. It stays hidden until you publish it.")
            % {"name": event.name},
        )
        return redirect("panel:event-index", slug=event.slug)

    def _events(self) -> list[EventDTO]:
        return self.request.services.sphere_panel.list_events(
            self.request.context.current_sphere_id
        )

    def _render(self, form: forms.Form, *, events: list[EventDTO]) -> HttpResponse:
        return TemplateResponse(
            self.request,
            "panel/event-create.html",
            {"events": events, "form": form, "active_nav": "event-create"},
        )
