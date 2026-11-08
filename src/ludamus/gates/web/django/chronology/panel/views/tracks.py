"""Track views (configurable lanes spanning spaces and managers)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.event.panel.views.base import (
    EventPanelMixin,
    PanelContext,
)
from ludamus.gates.web.django.forms import TrackForm
from ludamus.gates.web.django.request_ids import parse_ids
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.tracks import (
    DuplicateTrackNameError,
    TrackFormData,
    TrackSelectionInvalidError,
)

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.gates.web.django.panel import PanelRequest
    from ludamus.pacts.tracks import TrackEditFormContextDTO


def _submitted_pks(request: PanelRequest, field: str) -> list[int]:
    return parse_ids(request.POST.getlist(field))


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


class TracksPageView(EventPanelMixin, View):
    """List tracks for an event."""

    request: PanelRequest

    def get(self, _request: PanelRequest, **_kwargs: str) -> HttpResponse:
        context = self.panel_context()

        context["active_nav"] = "tracks"
        context["tracks"] = self.request.services.tracks_panel.list_tracks(
            self.current_event.pk
        )
        return TemplateResponse(self.request, "panel/tracks.html", context)


class TrackCreatePageView(EventPanelMixin, View):
    """Create a new track for an event."""

    request: PanelRequest

    def get(self, _request: PanelRequest, **_kwargs: str) -> HttpResponse:
        context = self.panel_context()

        form_context = self.request.services.tracks_panel.get_form_context(
            event_pk=self.current_event.pk,
            sphere_id=self.request.context.current_sphere_id,
        )
        context["active_nav"] = "tracks"
        context["form"] = TrackForm(initial={"is_public": True})
        context["spaces"] = form_context.spaces
        context["managers"] = form_context.managers
        context["selected_space_pks"] = []
        context["selected_manager_pks"] = []
        return TemplateResponse(self.request, "panel/track-create.html", context)

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context = self.panel_context()

        service = self.request.services.tracks_panel
        sphere_id = self.request.context.current_sphere_id
        form = TrackForm(self.request.POST)

        if not form.is_valid():
            return self._rerender_create_form(
                context=context,
                form=form,
                event_pk=self.current_event.pk,
                sphere_id=sphere_id,
            )

        try:
            service.create(
                event_pk=self.current_event.pk,
                sphere_id=sphere_id,
                data=_submitted_track_data(request=self.request, form=form),
            )
        except TrackSelectionInvalidError:
            form.add_error(
                None, _("Choose spaces from this event and managers from this sphere.")
            )
        except DuplicateTrackNameError:
            _add_duplicate_name_error(form)
        else:
            messages.success(self.request, _("Track created successfully."))
            return redirect("panel:tracks", slug=slug)
        return self._rerender_create_form(
            context=context,
            form=form,
            event_pk=self.current_event.pk,
            sphere_id=sphere_id,
        )

    def _rerender_create_form(
        self, *, context: PanelContext, form: TrackForm, event_pk: int, sphere_id: int
    ) -> HttpResponse:
        form_context = self.request.services.tracks_panel.get_form_context(
            event_pk=event_pk, sphere_id=sphere_id
        )
        context["active_nav"] = "tracks"
        context["form"] = form
        context["spaces"] = form_context.spaces
        context["managers"] = form_context.managers
        context["selected_space_pks"] = _submitted_pks(self.request, "space_pks")
        context["selected_manager_pks"] = _submitted_pks(self.request, "manager_pks")
        return TemplateResponse(self.request, "panel/track-create.html", context)


class TrackEditPageView(EventPanelMixin, View):
    """Edit an existing track."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str, track_slug: str) -> HttpResponse:
        context = self.panel_context()

        try:
            edit_context = self.request.services.tracks_panel.get_edit_context(
                event_pk=self.current_event.pk,
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
        context = self.panel_context()

        service = self.request.services.tracks_panel
        sphere_id = self.request.context.current_sphere_id
        # Read the track before touching the form, so a stale slug redirects
        # from one obvious place instead of from whichever render happens to
        # ask for it first.
        try:
            edit_context = service.get_edit_form_context(
                event_pk=self.current_event.pk,
                sphere_id=sphere_id,
                track_slug=track_slug,
            )
        except NotFoundError:
            messages.error(self.request, _("Track not found."))
            return redirect("panel:tracks", slug=slug)

        form = TrackForm(self.request.POST)
        if form.is_valid():
            try:
                service.update(
                    event_pk=self.current_event.pk,
                    sphere_id=sphere_id,
                    track_slug=track_slug,
                    data=_submitted_track_data(request=self.request, form=form),
                )
            except TrackSelectionInvalidError:
                form.add_error(
                    None,
                    _("Choose spaces from this event and managers from this sphere."),
                )
            except DuplicateTrackNameError:
                _add_duplicate_name_error(form)
            except NotFoundError:
                messages.error(self.request, _("Track not found."))
                return redirect("panel:tracks", slug=slug)
            else:
                messages.success(self.request, _("Track updated successfully."))
                return redirect("panel:tracks", slug=slug)

        return self._render_edit_form(
            context=context, form=form, edit_context=edit_context
        )

    def _render_edit_form(
        self,
        *,
        context: PanelContext,
        form: TrackForm,
        edit_context: TrackEditFormContextDTO,
    ) -> HttpResponse:
        context["active_nav"] = "tracks"
        context["track"] = edit_context.track
        context["form"] = form
        context["spaces"] = edit_context.spaces
        context["managers"] = edit_context.managers
        context["selected_space_pks"] = _submitted_pks(self.request, "space_pks")
        context["selected_manager_pks"] = _submitted_pks(self.request, "manager_pks")
        return TemplateResponse(self.request, "panel/track-edit.html", context)


class TrackDeleteActionView(EventPanelMixin, View):
    """Delete a track (POST only)."""

    request: PanelRequest
    http_method_names = ("post",)

    def post(self, _request: PanelRequest, slug: str, track_slug: str) -> HttpResponse:
        try:
            self.request.services.tracks_panel.delete(
                event_pk=self.current_event.pk, track_slug=track_slug
            )
        except NotFoundError:
            messages.error(self.request, _("Track not found."))
            return redirect("panel:tracks", slug=slug)

        messages.success(self.request, _("Track deleted."))
        return redirect("panel:tracks", slug=slug)
