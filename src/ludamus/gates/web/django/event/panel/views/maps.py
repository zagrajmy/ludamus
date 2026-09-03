"""Panel "Maps": uploaded venue plans and the spaces drawn on each."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.event.panel.views.base import (
    EventContextMixin,
    EventPanelAccessMixin,
    EventPanelRequest,
)
from ludamus.gates.web.django.forms import create_event_map_form
from ludamus.pacts import NotFoundError
from ludamus.pacts.images import stored_file
from ludamus.pacts.legacy import parse_uploaded_file
from ludamus.pacts.maps import EventMapInputDTO

if TYPE_CHECKING:
    from django import forms
    from django.http import HttpResponse

    from ludamus.pacts import EventDTO
    from ludamus.pacts.maps import EventMapDTO


def _space_choices(request: EventPanelRequest, event_pk: int) -> list[tuple[str, str]]:
    return [
        (str(scope.pk), scope.name)
        for scope in request.services.venues.list_print_scopes(event_pk)
    ]


def _submitted(form: forms.Form) -> EventMapInputDTO:
    return EventMapInputDTO(
        name=form.cleaned_data["name"],
        space_pks=[int(pk) for pk in form.cleaned_data["spaces"]],
    )


class MapsPageView(EventPanelAccessMixin, EventContextMixin, View):
    request: EventPanelRequest

    def get(self, _request: EventPanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")
        context["active_nav"] = "maps"
        context["maps"] = self.request.services.event_maps.list_for_event(
            current_event.pk
        )
        return TemplateResponse(self.request, "panel/maps.html", context)


class MapCreatePageView(EventPanelAccessMixin, EventContextMixin, View):
    request: EventPanelRequest

    def get(self, _request: EventPanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")
        context["active_nav"] = "maps"
        context["event_map"] = None
        context["form"] = self._form(current_event.pk)()
        return TemplateResponse(self.request, "panel/map-form.html", context)

    def _form(self, event_pk: int) -> type[forms.Form]:
        return create_event_map_form(
            space_choices=_space_choices(self.request, event_pk), has_image=False
        )

    def post(self, _request: EventPanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")
        form = self._form(current_event.pk)(self.request.POST, self.request.FILES)
        if form.is_valid() and (
            image := parse_uploaded_file(form.cleaned_data.get("image"))
        ):
            try:
                self.request.services.event_maps.create(
                    event_pk=current_event.pk, data=_submitted(form), image=image
                )
            except NotFoundError:
                form.add_error("spaces", _("Pick venues of this event."))
            else:
                messages.success(self.request, _("Map added."))
                return redirect("panel:maps", slug=slug)
        context["active_nav"] = "maps"
        context["event_map"] = None
        context["form"] = form
        return TemplateResponse(self.request, "panel/map-form.html", context)


class MapEditPageView(EventPanelAccessMixin, EventContextMixin, View):
    request: EventPanelRequest

    def _read(self, current_event: EventDTO, pk: int) -> EventMapDTO | None:
        try:
            return self.request.services.event_maps.read(
                event_pk=current_event.pk, pk=pk
            )
        except NotFoundError:
            messages.error(self.request, _("Map not found."))
            return None

    def get(self, _request: EventPanelRequest, slug: str, pk: int) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")
        if (event_map := self._read(current_event, pk)) is None:
            return redirect("panel:maps", slug=slug)
        context["active_nav"] = "maps"
        context["event_map"] = event_map
        context["form"] = self._form(current_event.pk)(
            initial={
                "name": event_map.name,
                "image": stored_file(
                    event_map.image_url, event_map.image_original_name
                ),
                "spaces": [str(space.pk) for space in event_map.spaces],
            }
        )
        return TemplateResponse(self.request, "panel/map-form.html", context)

    def _form(self, event_pk: int) -> type[forms.Form]:
        return create_event_map_form(
            space_choices=_space_choices(self.request, event_pk), has_image=True
        )

    def post(self, _request: EventPanelRequest, slug: str, pk: int) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")
        if (event_map := self._read(current_event, pk)) is None:
            return redirect("panel:maps", slug=slug)
        form = self._form(current_event.pk)(self.request.POST, self.request.FILES)
        if form.is_valid():
            try:
                self.request.services.event_maps.update(
                    event_pk=current_event.pk,
                    pk=pk,
                    data=_submitted(form),
                    image=parse_uploaded_file(form.cleaned_data.get("image")),
                )
            except NotFoundError:
                form.add_error("spaces", _("Pick venues of this event."))
            else:
                messages.success(self.request, _("Map saved."))
                return redirect("panel:maps", slug=slug)
        context["active_nav"] = "maps"
        context["event_map"] = event_map
        context["form"] = form
        return TemplateResponse(self.request, "panel/map-form.html", context)


class MapDeleteActionView(EventPanelAccessMixin, EventContextMixin, View):
    request: EventPanelRequest
    http_method_names = ("post",)

    def post(self, _request: EventPanelRequest, slug: str, pk: int) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")
        try:
            self.request.services.event_maps.delete(event_pk=current_event.pk, pk=pk)
        except NotFoundError:
            messages.error(self.request, _("Map not found."))
        else:
            messages.success(self.request, _("Map deleted."))
        return redirect("panel:maps", slug=slug)
