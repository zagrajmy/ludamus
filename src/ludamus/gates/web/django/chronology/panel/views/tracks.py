# pylint: disable=duplicate-code
# TODO(fancysnake): Extract common view boilerplate

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
from ludamus.pacts import NotFoundError
from ludamus.pacts.tracks import DuplicateTrackNameError, TrackFormData

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.pacts import EventDTO


def _submitted_pks(request: PanelRequest, field: str) -> list[int]:
    return [int(pk) for pk in request.POST.getlist(field) if pk.isdigit()]


def _add_duplicate_name_error(form: TrackForm) -> None:
    msg = _("A track with this name already exists in this event. Pick another name.")
    form.add_error("name", msg)


def _submitted_track_data(*, request: PanelRequest, form: TrackForm) -> TrackFormData:
    return TrackFormData(
        name=form.cleaned_data["name"],
        is_public=form.cleaned_data["is_public"],
        space_pks=_submitted_pks(request, "space_pks"),
        manager_pks=_submitted_pks(request, "manager_pks"),
    )


class TracksPageView(PanelAccessMixin, EventContextMixin, View):
    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        context["active_nav"] = "tracks"
        context["tracks"] = self.request.services.tracks_panel.list_tracks(
            current_event.pk
        )
        return TemplateResponse(self.request, "panel/tracks.html", context)


class TrackCreatePageView(PanelAccessMixin, EventContextMixin, View):
    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        form = TrackForm(initial={"is_public": True})
        return self._render_form(context=context, event_pk=current_event.pk, form=form)

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        form = TrackForm(self.request.POST)
        if form.is_valid():
            try:
                self.request.services.tracks_panel.create(
                    event_pk=current_event.pk,
                    sphere_id=self.request.context.current_sphere_id,
                    data=_submitted_track_data(request=self.request, form=form),
                )
            except DuplicateTrackNameError:
                _add_duplicate_name_error(form)
            else:
                messages.success(self.request, _("Track created successfully."))
                return redirect("panel:tracks", slug=slug)

        return self._render_form(context=context, event_pk=current_event.pk, form=form)

    def _render_form(
        self, *, context: dict[str, object], event_pk: int, form: TrackForm
    ) -> HttpResponse:
        form_context = self.request.services.tracks_panel.get_form_context(
            event_pk=event_pk, sphere_id=self.request.context.current_sphere_id
        )
        context["active_nav"] = "tracks"
        context["form"] = form
        context["spaces"] = form_context.spaces
        context["managers"] = form_context.managers
        context["selected_space_pks"] = _submitted_pks(self.request, "space_pks")
        context["selected_manager_pks"] = _submitted_pks(self.request, "manager_pks")
        return TemplateResponse(self.request, "panel/track-create.html", context)


class TrackEditPageView(PanelAccessMixin, EventContextMixin, View):
    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str, track_slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        try:
            edit_context = self.request.services.tracks_panel.get_edit_context(
                event_pk=current_event.pk,
                sphere_id=self.request.context.current_sphere_id,
                track_slug=track_slug,
            )
        except NotFoundError:
            messages.error(self.request, _("Track not found."))
            return redirect("panel:tracks", slug=slug)

        track = edit_context.track
        context["active_nav"] = "tracks"
        context["track"] = track
        context["form"] = TrackForm(
            initial={"name": track.name, "is_public": track.is_public}
        )
        context["spaces"] = edit_context.spaces
        context["managers"] = edit_context.managers
        context["selected_space_pks"] = edit_context.selected_space_pks
        context["selected_manager_pks"] = edit_context.selected_manager_pks
        return TemplateResponse(self.request, "panel/track-edit.html", context)

    def post(self, _request: PanelRequest, slug: str, track_slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        try:
            return self._saved_or_rerendered(
                context=context,
                form=TrackForm(self.request.POST),
                event=current_event,
                track_slug=track_slug,
            )
        except NotFoundError:
            messages.error(self.request, _("Track not found."))
            return redirect("panel:tracks", slug=slug)

    def _saved_or_rerendered(
        self,
        *,
        context: dict[str, object],
        form: TrackForm,
        event: EventDTO,
        track_slug: str,
    ) -> HttpResponse:
        if form.is_valid():
            try:
                self.request.services.tracks_panel.update(
                    event_pk=event.pk,
                    sphere_id=self.request.context.current_sphere_id,
                    track_slug=track_slug,
                    data=_submitted_track_data(request=self.request, form=form),
                )
            except DuplicateTrackNameError:
                _add_duplicate_name_error(form)
            else:
                messages.success(self.request, _("Track updated successfully."))
                return redirect("panel:tracks", slug=event.slug)

        return self._rerender_edit_form(
            context=context, form=form, event_pk=event.pk, track_slug=track_slug
        )

    def _rerender_edit_form(
        self,
        *,
        context: dict[str, object],
        form: TrackForm,
        event_pk: int,
        track_slug: str,
    ) -> HttpResponse:
        edit_context = self.request.services.tracks_panel.get_edit_form_context(
            event_pk=event_pk,
            sphere_id=self.request.context.current_sphere_id,
            track_slug=track_slug,
        )
        context["active_nav"] = "tracks"
        context["track"] = edit_context.track
        context["form"] = form
        context["spaces"] = edit_context.spaces
        context["managers"] = edit_context.managers
        context["selected_space_pks"] = _submitted_pks(self.request, "space_pks")
        context["selected_manager_pks"] = _submitted_pks(self.request, "manager_pks")
        return TemplateResponse(self.request, "panel/track-edit.html", context)


class TrackDeleteActionView(PanelAccessMixin, EventContextMixin, View):
    request: PanelRequest
    http_method_names = ("post",)

    def post(self, _request: PanelRequest, slug: str, track_slug: str) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        try:
            self.request.services.tracks_panel.delete(
                event_pk=current_event.pk, track_slug=track_slug
            )
        except NotFoundError:
            messages.error(self.request, _("Track not found."))
            return redirect("panel:tracks", slug=slug)

        messages.success(self.request, _("Track deleted."))
        return redirect("panel:tracks", slug=slug)
