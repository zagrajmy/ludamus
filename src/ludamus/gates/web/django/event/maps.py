"""Event maps page: one page for everyone, with editing controls for organizers.

A viewer sees every plan with its venues; an organizer sees the same page plus
"Add map", per-map edit and delete, and "Attach venue". Each control opens an
addressable modal (`?add-map=1`, `?edit-map=<pk>`, `?attach=<pk>`), and a
failed post re-renders the page at that address so the dialog reopens with its
errors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.access import panel_access, passes_panel_access
from ludamus.gates.web.django.forms import create_event_map_form, create_map_spaces_form
from ludamus.gates.web.django.helpers import is_event_published
from ludamus.gates.web.django.panel import refuse_panel_access
from ludamus.gates.web.django.sphere.pages import EventsPageRequiredMixin
from ludamus.pacts import NotFoundError
from ludamus.pacts.images import stored_file
from ludamus.pacts.legacy import parse_uploaded_file
from ludamus.pacts.multiverse import Capability

if TYPE_CHECKING:
    from django import forms
    from django.http import HttpResponse

    from ludamus.gates.web.django.entities import RootRequest
    from ludamus.pacts import EventDTO
    from ludamus.pacts.maps import EventMapDTO


@dataclass
class MapCard:
    # One plan as the page renders it, with the organizer's two dialogs bound
    # to it. Both forms exist for viewers too — they render nothing without
    # can_edit — so the template never branches on their presence.
    map: EventMapDTO
    edit_form: forms.Form
    attach_form: forms.Form


def _read_event(request: RootRequest, slug: str) -> EventDTO:
    try:
        event = request.services.events.read_by_slug(
            request.context.current_sphere_id, slug
        )
    except NotFoundError as exc:
        raise Http404 from exc
    if not is_event_published(event) and not panel_access(request).granted:
        raise Http404
    return event


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
    can_edit = panel_access(request).granted
    space_choices = _space_choices(request, event.pk) if can_edit else []
    edit_forms = edit_forms or {}
    attach_forms = attach_forms or {}
    cards = []
    for event_map in request.services.event_maps.list_for_event(event.pk):
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
            "add_form": add_form or create_event_map_form(has_image=False)(),
            "schedule_url": reverse(
                "web:chronology:event", kwargs={"slug": event.slug}
            ),
        },
    )


class EventMapsPageView(EventsPageRequiredMixin, View):
    request: RootRequest

    @staticmethod
    def get(request: RootRequest, slug: str) -> HttpResponse:
        return render_maps_page(request, _read_event(request, slug))


def _refused(request: RootRequest) -> HttpResponse | None:
    # Organizer-only writes on a public page: the page itself is open to
    # everyone, so each action checks the write capability on arrival rather
    # than inheriting a panel mixin's login redirect.
    if passes_panel_access(request, write_capability=Capability.PANEL_WRITE):
        return None
    return refuse_panel_access(
        request=request,
        reads_panel=panel_access(request).granted,
        message=_("Only the event's organizers can change its maps."),
    )


class _MapWriteView(EventsPageRequiredMixin, View):
    request: RootRequest
    http_method_names = ("post",)


class EventMapAddActionView(_MapWriteView):
    @staticmethod
    def post(request: RootRequest, slug: str) -> HttpResponse:
        if refused := _refused(request):
            return refused
        event = _read_event(request, slug)
        form = create_event_map_form(has_image=False)(request.POST, request.FILES)
        if form.is_valid() and (
            image := parse_uploaded_file(form.cleaned_data.get("image"))
        ):
            request.services.event_maps.create(
                event_pk=event.pk, name=form.cleaned_data["name"], image=image
            )
            messages.success(request, _("Map added."))
            return redirect(_maps_url(slug))
        return render_maps_page(request, event, add_form=form)


class EventMapEditActionView(_MapWriteView):
    @staticmethod
    def post(request: RootRequest, slug: str, pk: int) -> HttpResponse:
        if refused := _refused(request):
            return refused
        event = _read_event(request, slug)
        form = create_event_map_form(has_image=True)(
            request.POST, request.FILES, auto_id=f"edit_map_{pk}_%s"
        )
        if not form.is_valid():
            return render_maps_page(request, event, edit_forms={pk: form})
        try:
            request.services.event_maps.update(
                event_pk=event.pk,
                pk=pk,
                name=form.cleaned_data["name"],
                image=parse_uploaded_file(form.cleaned_data.get("image")),
            )
        except NotFoundError:
            messages.error(request, _("Map not found."))
        else:
            messages.success(request, _("Map saved."))
        return redirect(_maps_url(slug))


class EventMapAttachActionView(_MapWriteView):
    @staticmethod
    def post(request: RootRequest, slug: str, pk: int) -> HttpResponse:
        if refused := _refused(request):
            return refused
        event = _read_event(request, slug)
        form = create_map_spaces_form(space_choices=_space_choices(request, event.pk))(
            request.POST, auto_id=f"attach_{pk}_%s"
        )
        if not form.is_valid():
            return render_maps_page(request, event, attach_forms={pk: form})
        try:
            request.services.event_maps.attach_spaces(
                event_pk=event.pk,
                pk=pk,
                space_pks=[int(space_pk) for space_pk in form.cleaned_data["spaces"]],
            )
        except NotFoundError:
            messages.error(request, _("Map not found."))
        else:
            messages.success(request, _("Venues on the map updated."))
        return redirect(_maps_url(slug))


class EventMapDeleteActionView(_MapWriteView):
    @staticmethod
    def post(request: RootRequest, slug: str, pk: int) -> HttpResponse:
        if refused := _refused(request):
            return refused
        event = _read_event(request, slug)
        try:
            request.services.event_maps.delete(event_pk=event.pk, pk=pk)
        except NotFoundError:
            messages.error(request, _("Map not found."))
        else:
            messages.success(request, _("Map deleted."))
        return redirect(_maps_url(slug))
