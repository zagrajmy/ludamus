"""Event maps page: one page for everyone, with editing controls for organizers.

A viewer sees every plan with its venues; an organizer sees the same page plus
"Add map", per-map edit and delete, and "Attach venue". Each control opens an
addressable modal (`?add-map=1`, `?edit-map=<pk>`, `?attach=<pk>`), and a
failed post re-renders the page at that address so the dialog reopens with its
errors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.access import panel_access
from ludamus.gates.web.django.forms import create_event_map_form, create_map_spaces_form
from ludamus.gates.web.django.helpers import read_public_event
from ludamus.gates.web.django.panel import refuse_panel_access
from ludamus.gates.web.django.sphere.pages import EventsPageRequiredMixin
from ludamus.pacts import NotFoundError
from ludamus.pacts.images import stored_file
from ludamus.pacts.legacy import parse_uploaded_file
from ludamus.pacts.multiverse import Capability

if TYPE_CHECKING:
    from django import forms
    from django.http import HttpRequest, HttpResponse, HttpResponseBase

    from ludamus.gates.web.django.entities import RootRequest
    from ludamus.pacts import EventDTO
    from ludamus.pacts.maps import EventMapDTO


@dataclass
class MapCard:
    map: EventMapDTO
    edit_form: forms.Form | None
    attach_form: forms.Form | None


def _space_choices(request: RootRequest, event_pk: int) -> list[tuple[str, str]]:
    return [
        (str(scope.pk), scope.name)
        for scope in request.services.venues.list_print_scopes(event_pk)
    ]


def _maps_url(slug: str) -> str:
    return reverse("web:chronology:event-maps", kwargs={"slug": slug})


def render_maps_page(
    request: RootRequest,
    event: EventDTO,
    *,
    add_form: forms.Form | None = None,
    edit_forms: dict[int, forms.Form] | None = None,
    attach_forms: dict[int, forms.Form] | None = None,
) -> HttpResponse:
    # The action views pass the form that failed so its dialog reopens with
    # the errors; every other dialog gets a fresh one.
    access = panel_access(request)
    can_edit = access.allows(Capability.PANEL_WRITE)
    space_choices = _space_choices(request, event.pk) if can_edit else []
    edit_forms = edit_forms or {}
    attach_forms = attach_forms or {}
    cards = []
    for event_map in request.services.event_maps.list_for_event(event.pk):
        edit_form = None
        attach_form = None
        if can_edit:
            edit_form = edit_forms.get(event_map.pk) or create_event_map_form(
                has_image=True
            )(
                auto_id=f"edit_map_{event_map.pk}_%s",
                initial={
                    "name": event_map.name,
                    "image": stored_file(
                        event_map.image_url, event_map.image_original_name
                    ),
                },
            )
            attach_form = attach_forms.get(event_map.pk) or create_map_spaces_form(
                space_choices=space_choices
            )(
                auto_id=f"attach_{event_map.pk}_%s",
                initial={"spaces": [str(pk) for pk in event_map.space_pks]},
            )
        cards.append(
            MapCard(map=event_map, edit_form=edit_form, attach_form=attach_form)
        )
    return TemplateResponse(
        request,
        "chronology/maps.html",
        {
            "event": event,
            "cards": cards,
            "can_edit": can_edit,
            "add_form": (
                add_form or create_event_map_form(has_image=False)()
                if can_edit
                else None
            ),
            "schedule_url": reverse(
                "web:chronology:event", kwargs={"slug": event.slug}
            ),
        },
    )


class EventMapsPageView(EventsPageRequiredMixin, View):
    request: RootRequest

    @staticmethod
    def get(request: RootRequest, slug: str) -> HttpResponse:
        return render_maps_page(request, read_public_event(request, slug))


class _MapWriteView(EventsPageRequiredMixin, View):
    # Organizer-only writes on a public page: the page itself is open to
    # everyone, so each action checks the write capability on arrival rather
    # than inheriting a panel mixin's login redirect. The event is read once
    # here from the slug, which the handlers then never see: they only act.
    request: RootRequest
    event: EventDTO
    http_method_names = ("post",)

    def dispatch(
        self, request: HttpRequest, *args: object, **kwargs: object
    ) -> HttpResponseBase:
        root_request = cast("RootRequest", request)
        access = panel_access(root_request)
        if not access.allows(Capability.PANEL_WRITE):
            return refuse_panel_access(
                request=root_request,
                reads_panel=access.granted,
                message=_("Only the event's organizers can change its maps."),
            )
        self.event = read_public_event(root_request, str(kwargs.pop("slug")))
        return super().dispatch(request, *args, **kwargs)

    def _done(self, outcome: str) -> HttpResponse:
        messages.success(self.request, outcome)
        return redirect(_maps_url(self.event.slug))

    def _not_found(self) -> HttpResponse:
        messages.error(self.request, _("Map not found."))
        return redirect(_maps_url(self.event.slug))


class EventMapAddActionView(_MapWriteView):
    def post(self, request: RootRequest) -> HttpResponse:
        form = create_event_map_form(has_image=False)(request.POST, request.FILES)
        if form.is_valid() and (
            image := parse_uploaded_file(form.cleaned_data.get("image"))
        ):
            request.services.event_maps.create(
                event_pk=self.event.pk, name=form.cleaned_data["name"], image=image
            )
            return self._done(_("Map added."))
        return render_maps_page(request, self.event, add_form=form)


class EventMapEditActionView(_MapWriteView):
    def post(self, request: RootRequest, pk: int) -> HttpResponse:
        form = create_event_map_form(has_image=True)(
            request.POST, request.FILES, auto_id=f"edit_map_{pk}_%s"
        )
        if not form.is_valid():
            return render_maps_page(request, self.event, edit_forms={pk: form})
        try:
            request.services.event_maps.update(
                event_pk=self.event.pk,
                pk=pk,
                name=form.cleaned_data["name"],
                image=parse_uploaded_file(form.cleaned_data.get("image")),
            )
        except NotFoundError:
            return self._not_found()
        return self._done(_("Map saved."))


class EventMapAttachActionView(_MapWriteView):
    def post(self, request: RootRequest, pk: int) -> HttpResponse:
        form = create_map_spaces_form(
            space_choices=_space_choices(request, self.event.pk)
        )(request.POST, auto_id=f"attach_{pk}_%s")
        if not form.is_valid():
            return render_maps_page(request, self.event, attach_forms={pk: form})
        try:
            request.services.event_maps.attach_spaces(
                event_pk=self.event.pk,
                pk=pk,
                space_pks=[int(space_pk) for space_pk in form.cleaned_data["spaces"]],
            )
        except NotFoundError:
            return self._not_found()
        return self._done(_("Venues on the map updated."))


class EventMapDeleteActionView(_MapWriteView):
    def post(self, request: RootRequest, pk: int) -> HttpResponse:
        try:
            request.services.event_maps.delete(event_pk=self.event.pk, pk=pk)
        except NotFoundError:
            return self._not_found()
        return self._done(_("Map deleted."))
