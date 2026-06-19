# pylint: disable=duplicate-code
# TODO(fancysnake): Extract common view boilerplate
"""Track views (configurable lanes spanning spaces and managers)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.chronology.panel.views.base import (
    EventContextMixin,
    PanelAccessMixin,
    PanelRequest,
)
from ludamus.gates.web.django.forms import TrackForm
from ludamus.pacts import NotFoundError, TrackCreateData, TrackUpdateData

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.pacts import SpaceDTO, UserDTO


def _track_get_choices(
    request: PanelRequest, event_pk: int, sphere_id: int
) -> tuple[list[SpaceDTO], list[UserDTO]]:
    spaces = request.di.uow.spaces.list_by_event(event_pk)
    managers = request.di.uow.spheres.list_managers(sphere_id)
    return spaces, managers


def _scoped_pks(request: PanelRequest, field: str, valid_pks: set[int]) -> list[int]:
    """Keep only the submitted pks that belong to the event/sphere.

    Returns:
        The intersection of the submitted ``field`` pks with ``valid_pks``,
        dropping any id that points outside the current event or sphere.
    """
    submitted = {int(pk) for pk in request.POST.getlist(field) if pk.isdigit()}
    return list(submitted & valid_pks)


class TracksPageView(PanelAccessMixin, EventContextMixin, View):
    """List tracks for an event."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        context["active_nav"] = "tracks"
        context["tracks"] = self.request.di.uow.tracks.list_by_event(current_event.pk)
        return TemplateResponse(self.request, "panel/tracks.html", context)


class TrackCreatePageView(PanelAccessMixin, EventContextMixin, View):
    """Create a new track for an event."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        sphere_id = self.request.context.current_sphere_id
        spaces, managers = _track_get_choices(self.request, current_event.pk, sphere_id)
        context["active_nav"] = "tracks"
        context["form"] = TrackForm(initial={"is_public": True})
        context["spaces"] = spaces
        context["managers"] = managers
        context["selected_space_pks"] = []
        context["selected_manager_pks"] = []
        return TemplateResponse(self.request, "panel/track-create.html", context)

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        sphere_id = self.request.context.current_sphere_id
        spaces, managers = _track_get_choices(self.request, current_event.pk, sphere_id)
        form = TrackForm(self.request.POST)

        if not form.is_valid():
            context["active_nav"] = "tracks"
            context["form"] = form
            context["spaces"] = spaces
            context["managers"] = managers
            context["selected_space_pks"] = [
                int(pk) for pk in self.request.POST.getlist("space_pks") if pk.isdigit()
            ]
            context["selected_manager_pks"] = [
                int(pk)
                for pk in self.request.POST.getlist("manager_pks")
                if pk.isdigit()
            ]
            return TemplateResponse(self.request, "panel/track-create.html", context)

        self.request.di.uow.tracks.create(
            TrackCreateData(
                event_pk=current_event.pk,
                name=form.cleaned_data["name"],
                is_public=form.cleaned_data.get("is_public", True),
                space_pks=_scoped_pks(
                    self.request, "space_pks", {s.pk for s in spaces}
                ),
                manager_pks=_scoped_pks(
                    self.request, "manager_pks", {m.pk for m in managers}
                ),
            )
        )
        messages.success(self.request, _("Track created successfully."))
        return redirect("panel:tracks", slug=slug)


class TrackEditPageView(PanelAccessMixin, EventContextMixin, View):
    """Edit an existing track."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str, track_slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        try:
            track = self.request.di.uow.tracks.read_by_slug(
                current_event.pk, track_slug
            )
        except NotFoundError:
            messages.error(self.request, _("Track not found."))
            return redirect("panel:tracks", slug=slug)

        sphere_id = self.request.context.current_sphere_id
        spaces, managers = _track_get_choices(self.request, current_event.pk, sphere_id)
        context["active_nav"] = "tracks"
        context["track"] = track
        context["form"] = TrackForm(
            initial={"name": track.name, "is_public": track.is_public}
        )
        context["spaces"] = spaces
        context["managers"] = managers
        context["selected_space_pks"] = self.request.di.uow.tracks.list_space_pks(
            track.pk
        )
        context["selected_manager_pks"] = self.request.di.uow.tracks.list_manager_pks(
            track.pk
        )
        return TemplateResponse(self.request, "panel/track-edit.html", context)

    def post(self, _request: PanelRequest, slug: str, track_slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        try:
            track = self.request.di.uow.tracks.read_by_slug(
                current_event.pk, track_slug
            )
        except NotFoundError:
            messages.error(self.request, _("Track not found."))
            return redirect("panel:tracks", slug=slug)

        sphere_id = self.request.context.current_sphere_id
        spaces, managers = _track_get_choices(self.request, current_event.pk, sphere_id)
        form = TrackForm(self.request.POST)

        if not form.is_valid():
            context["active_nav"] = "tracks"
            context["track"] = track
            context["form"] = form
            context["spaces"] = spaces
            context["managers"] = managers
            context["selected_space_pks"] = [
                int(pk) for pk in self.request.POST.getlist("space_pks") if pk.isdigit()
            ]
            context["selected_manager_pks"] = [
                int(pk)
                for pk in self.request.POST.getlist("manager_pks")
                if pk.isdigit()
            ]
            return TemplateResponse(self.request, "panel/track-edit.html", context)

        self.request.di.uow.tracks.update(
            track.pk,
            TrackUpdateData(
                name=form.cleaned_data["name"],
                is_public=form.cleaned_data.get("is_public", False),
                space_pks=_scoped_pks(
                    self.request, "space_pks", {s.pk for s in spaces}
                ),
                manager_pks=_scoped_pks(
                    self.request, "manager_pks", {m.pk for m in managers}
                ),
            ),
        )

        messages.success(self.request, _("Track updated successfully."))
        return redirect("panel:tracks", slug=slug)


class TrackDeleteActionView(PanelAccessMixin, EventContextMixin, View):
    """Delete a track (POST only)."""

    request: PanelRequest
    http_method_names = ("post",)

    def post(self, _request: PanelRequest, slug: str, track_slug: str) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        try:
            track = self.request.di.uow.tracks.read_by_slug(
                current_event.pk, track_slug
            )
        except NotFoundError:
            messages.error(self.request, _("Track not found."))
            return redirect("panel:tracks", slug=slug)

        self.request.di.uow.tracks.delete(track.pk)
        messages.success(self.request, _("Track deleted."))
        return redirect("panel:tracks", slug=slug)
