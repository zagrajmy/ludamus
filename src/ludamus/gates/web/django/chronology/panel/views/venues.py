# pylint: disable=duplicate-code
"""Recursive Space-tree CRUD for the panel "Venues" section."""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.chronology.panel.views.base import (
    EventContextMixin,
    PanelAccessMixin,
    PanelRequest,
)
from ludamus.gates.web.django.forms import (
    SpaceEditForm,
    SpaceForm,
    create_space_copy_form,
)
from ludamus.pacts import NotFoundError
from ludamus.pacts.venues import SpaceInputDTO, SpaceValidationError

if TYPE_CHECKING:
    from collections.abc import Iterable
    from typing import TypedDict

    from django import forms
    from django.http import HttpResponse

    from ludamus.pacts.venues import ProgrammeSpaceRowDTO, SpaceRecordDTO

    class ProgrammeTrackTone(TypedDict):
        name: str
        classes: str

    class ProgrammeSpaceRow(TypedDict):
        space: ProgrammeSpaceRowDTO
        tracks: list[ProgrammeTrackTone]

    class LocationCrumb(TypedDict):
        name: str
        space_filter: None

    class LocationPreview(TypedDict):
        location_label: str
        location_crumbs: list[LocationCrumb]


logger = logging.getLogger(__name__)

_TRACK_TONES = (
    "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200",
    "bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-200",
    "bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-200",
    "bg-lime-100 text-lime-800 dark:bg-lime-900/40 dark:text-lime-200",
    "bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-200",
    "bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-200",
    "bg-pink-100 text-pink-800 dark:bg-pink-900/40 dark:text-pink-200",
    "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200",
    "bg-cyan-100 text-cyan-800 dark:bg-cyan-900/40 dark:text-cyan-200",
    "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-200",
    "bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-200",
    "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-200",
    "bg-teal-100 text-teal-800 dark:bg-teal-900/40 dark:text-teal-200",
)


def build_track_tone_map(track_names: Iterable[str]) -> dict[str, str]:
    return {
        name: _TRACK_TONES[index % len(_TRACK_TONES)]
        for index, name in enumerate(sorted(set(track_names), key=str.casefold))
    }


def _programme_rows(spaces: list[ProgrammeSpaceRowDTO]) -> list[ProgrammeSpaceRow]:
    tone_by_name = build_track_tone_map(
        name for space in spaces for name in space.track_names
    )
    return [
        {
            "space": space,
            "tracks": [
                {"name": name, "classes": tone_by_name[name]}
                for name in space.track_names
            ],
        }
        for space in spaces
    ]


def _location_preview(space: ProgrammeSpaceRowDTO | None) -> LocationPreview | None:
    if space is None:
        return None
    return {
        "location_label": space.path,
        "location_crumbs": [
            {"name": name, "space_filter": None} for name in space.path.split(" > ")
        ],
    }


def suggest_copy_name(name: str) -> str:
    # Bump an existing "(Copy)" / "(Copy N)" suffix instead of stacking them.
    if match := re.match(r"^(.+?) \(Copy(?: (\d+))?\)$", name):
        base = match.group(1)
        num = int(match.group(2) or 1) + 1
        return f"{base} (Copy {num})"
    return f"{name} (Copy)"


class SpacesPageView(PanelAccessMixin, EventContextMixin, View):
    """Render the whole space tree for an event."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        active_tab = (
            "programme" if self.request.GET.get("view") == "programme" else "layout"
        )
        tree = (
            self.request.services.space_tree.list_tree(current_event.pk)
            if active_tab == "layout"
            else []
        )
        programme_spaces = self.request.services.space_tree.list_programme_spaces(
            current_event.pk
        )
        longest_space = max(
            programme_spaces,
            key=lambda space: (len(space.path), space.path),
            default=None,
        )
        venues_url = reverse("panel:venues", kwargs={"slug": current_event.slug})
        context["active_nav"] = "venues"
        context["active_tab"] = active_tab
        context["layout_url"] = venues_url
        context["programme_url"] = f"{venues_url}?view=programme"
        context["tree"] = tree
        context["has_nested_spaces"] = any(node.children for node in tree)
        context["programme_spaces"] = _programme_rows(programme_spaces)
        context["location_preview"] = _location_preview(longest_space)
        return TemplateResponse(self.request, "panel/spaces.html", context)


class SpaceCreatePageView(PanelAccessMixin, EventContextMixin, View):
    """Create a node, optionally under a parent (parent_pk in the URL)."""

    request: PanelRequest

    def _parent(
        self, current_event_pk: int, parent_pk: int | None
    ) -> SpaceRecordDTO | None:
        if parent_pk is None:
            return None
        parent = self.request.services.space_tree.read(parent_pk)
        if parent.event_id != current_event_pk:
            raise NotFoundError
        return parent

    def get(
        self, _request: PanelRequest, slug: str, parent_pk: int | None = None
    ) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")
        try:
            parent = self._parent(current_event.pk, parent_pk)
        except NotFoundError:
            messages.error(self.request, _("Space not found."))
            return redirect("panel:venues", slug=slug)

        context["active_nav"] = "venues"
        context["parent"] = parent
        context["node"] = None
        context["form"] = SpaceForm()
        return TemplateResponse(self.request, "panel/space-form.html", context)

    def post(
        self, _request: PanelRequest, slug: str, parent_pk: int | None = None
    ) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")
        try:
            parent = self._parent(current_event.pk, parent_pk)
        except NotFoundError:
            messages.error(self.request, _("Space not found."))
            return redirect("panel:venues", slug=slug)

        form = SpaceForm(self.request.POST)
        if form.is_valid():
            try:
                self.request.services.space_tree.create(
                    event_id=current_event.pk,
                    parent_id=parent.pk if parent else None,
                    data=SpaceInputDTO(
                        name=form.cleaned_data["name"],
                        capacity=form.cleaned_data.get("capacity"),
                        description=form.cleaned_data.get("description") or "",
                        location=form.cleaned_data.get("location") or "",
                    ),
                )
            except SpaceValidationError as error:
                form.add_error(None, str(error))
            else:
                messages.success(self.request, _("Space created successfully."))
                return redirect("panel:venues", slug=slug)

        context["active_nav"] = "venues"
        context["parent"] = parent
        context["node"] = None
        context["form"] = form
        return TemplateResponse(self.request, "panel/space-form.html", context)


class SpaceEditPageView(PanelAccessMixin, EventContextMixin, View):
    """Edit a single node."""

    request: PanelRequest

    def _node(self, current_event_pk: int, pk: int) -> SpaceRecordDTO:
        node = self.request.services.space_tree.read(pk)
        if node.event_id != current_event_pk:
            raise NotFoundError
        return node

    def _parent_choices(self, node_pk: int, event_pk: int) -> list[tuple[str, str]]:
        # "Top level" (empty value) reparents to root; the rest are eligible
        # targets (no self, no descendants, no session-holding spaces).
        targets = self.request.services.space_tree.list_reparent_targets(
            pk=node_pk, event_pk=event_pk
        )
        return [("", _("Top level"))] + [(str(pk), name) for pk, name in targets]

    def get(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")
        try:
            node = self._node(current_event.pk, pk)
        except NotFoundError:
            messages.error(self.request, _("Space not found."))
            return redirect("panel:venues", slug=slug)

        form = SpaceEditForm(
            initial={
                "name": node.name,
                "capacity": node.capacity,
                "description": node.description,
                "location": node.location,
                "parent": node.parent_id or "",
            },
            parent_choices=self._parent_choices(node.pk, current_event.pk),
        )
        context["active_nav"] = "venues"
        context["parent"] = None
        context["node"] = node
        context["form"] = form
        return TemplateResponse(self.request, "panel/space-form.html", context)

    def post(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")
        try:
            node = self._node(current_event.pk, pk)
        except NotFoundError:
            messages.error(self.request, _("Space not found."))
            return redirect("panel:venues", slug=slug)

        form = SpaceEditForm(
            self.request.POST,
            parent_choices=self._parent_choices(node.pk, current_event.pk),
        )
        if form.is_valid():
            parent_raw = form.cleaned_data.get("parent")
            try:
                self.request.services.space_tree.update(
                    pk=node.pk,
                    parent_id=int(parent_raw) if parent_raw else None,
                    data=SpaceInputDTO(
                        name=form.cleaned_data["name"],
                        capacity=form.cleaned_data.get("capacity"),
                        description=form.cleaned_data.get("description") or "",
                        location=form.cleaned_data.get("location") or "",
                    ),
                )
            except SpaceValidationError as error:
                form.add_error(None, str(error))
            else:
                messages.success(self.request, _("Space updated successfully."))
                return redirect("panel:venues", slug=slug)

        context["active_nav"] = "venues"
        context["parent"] = None
        context["node"] = node
        context["form"] = form
        return TemplateResponse(self.request, "panel/space-form.html", context)


class SpaceDeleteActionView(PanelAccessMixin, EventContextMixin, View):
    """Delete a node and its subtree (POST only)."""

    request: PanelRequest
    http_method_names = ("post",)

    def post(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")
        try:
            node = self.request.services.space_tree.read(pk)
        except NotFoundError:
            messages.error(self.request, _("Space not found."))
            return redirect("panel:venues", slug=slug)
        if node.event_id != current_event.pk:
            messages.error(self.request, _("Space not found."))
            return redirect("panel:venues", slug=slug)

        if not self.request.services.space_tree.delete_space(node.pk):
            messages.error(
                self.request, _("Cannot delete a space with scheduled sessions.")
            )
            return redirect("panel:venues", slug=slug)

        messages.success(self.request, _("Space deleted successfully."))
        return redirect("panel:venues", slug=slug)


class SpaceDuplicateActionView(PanelAccessMixin, EventContextMixin, View):
    """Duplicate a node's subtree under the same parent (POST only)."""

    request: PanelRequest
    http_method_names = ("post",)

    def post(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")
        try:
            node = self.request.services.space_tree.read(pk)
        except NotFoundError:
            messages.error(self.request, _("Space not found."))
            return redirect("panel:venues", slug=slug)
        if node.event_id != current_event.pk:
            messages.error(self.request, _("Space not found."))
            return redirect("panel:venues", slug=slug)

        self.request.services.space_tree.duplicate(
            pk=node.pk, new_name=suggest_copy_name(node.name)
        )
        messages.success(self.request, _("Space duplicated successfully."))
        return redirect("panel:venues", slug=slug)


class SpaceCopyPageView(PanelAccessMixin, EventContextMixin, View):
    """Copy a node's subtree into another event as a new root."""

    request: PanelRequest

    def _node_and_choices(
        self, context: dict[str, Any], current_event_pk: int, pk: int
    ) -> tuple[SpaceRecordDTO, list[tuple[int, str]]]:
        node = self.request.services.space_tree.read(pk)
        if node.event_id != current_event_pk:
            raise NotFoundError
        choices = [
            (event.pk, event.name)
            for event in context["events"]
            if event.pk != current_event_pk
        ]
        return node, choices

    def _render(
        self, *, context: dict[str, Any], node: SpaceRecordDTO, form: forms.Form
    ) -> HttpResponse:
        context["active_nav"] = "venues"
        context["node"] = node
        context["form"] = form
        return TemplateResponse(self.request, "panel/space-copy.html", context)

    def get(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")
        try:
            node, choices = self._node_and_choices(context, current_event.pk, pk)
        except NotFoundError:
            messages.error(self.request, _("Space not found."))
            return redirect("panel:venues", slug=slug)
        if not choices:
            messages.warning(self.request, _("No other events available to copy to."))
            return redirect("panel:venues", slug=slug)

        form = create_space_copy_form(choices)()
        return self._render(context=context, node=node, form=form)

    def post(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")
        try:
            node, choices = self._node_and_choices(context, current_event.pk, pk)
        except NotFoundError:
            messages.error(self.request, _("Space not found."))
            return redirect("panel:venues", slug=slug)

        form = create_space_copy_form(choices)(self.request.POST)
        if not form.is_valid():
            return self._render(context=context, node=node, form=form)

        target_event_id = int(form.cleaned_data["target_event"])
        target_name = next(
            (name for event_pk, name in choices if event_pk == target_event_id), ""
        )
        self.request.services.space_tree.copy_to_event(
            pk=node.pk, target_event_id=target_event_id
        )
        messages.success(
            self.request,
            _("Space copied to %(event)s successfully.") % {"event": target_name},
        )
        return redirect("panel:venues", slug=slug)


class ProgrammeSpaceReorderActionView(PanelAccessMixin, View):
    """Reorder every directly scheduled space across the event."""

    request: PanelRequest
    http_method_names = ("post",)

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        sphere_id = self.request.context.current_sphere_id
        try:
            event = self.request.services.events.read_by_slug(sphere_id, slug)
        except NotFoundError:
            return JsonResponse({"error": "Event not found"}, status=404)

        try:
            data = json.loads(self.request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)
        space_ids = data.get("space_ids") if isinstance(data, dict) else None
        if not isinstance(space_ids, list) or not all(
            isinstance(pk, int) for pk in space_ids
        ):
            return JsonResponse({"error": "Invalid space_ids"}, status=400)

        try:
            self.request.services.space_tree.reorder_programme(
                event_id=event.pk, space_pks=space_ids
            )
        except SpaceValidationError as error:
            return JsonResponse({"error": str(error)}, status=400)
        logger.info(
            "Reordered programme spaces",
            extra={"event_id": event.pk, "space_count": len(space_ids)},
        )
        return JsonResponse({"success": True})


class SpaceMoveToRootActionView(PanelAccessMixin, View):
    """Move one event space from its parent to the top level."""

    request: PanelRequest
    http_method_names = ("post",)

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        sphere_id = self.request.context.current_sphere_id
        try:
            event = self.request.services.events.read_by_slug(sphere_id, slug)
        except NotFoundError:
            return JsonResponse({"error": "Event not found"}, status=404)

        try:
            data = json.loads(self.request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)
        space_id = data.get("space_id") if isinstance(data, dict) else None
        if not isinstance(space_id, int):
            return JsonResponse({"error": "Invalid space_id"}, status=400)

        try:
            self.request.services.space_tree.move_to_top_level(
                event_id=event.pk, space_pk=space_id
            )
        except NotFoundError:
            return JsonResponse({"error": "Space not found"}, status=404)
        except SpaceValidationError as error:
            return JsonResponse({"error": str(error)}, status=400)
        logger.info(
            "Moved space to top level",
            extra={"event_id": event.pk, "space_id": space_id},
        )
        return JsonResponse({"success": True})


class SpaceReorderActionView(PanelAccessMixin, View):
    """Reorder siblings under one parent (POST only, JSON)."""

    request: PanelRequest
    http_method_names = ("post",)

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        sphere_id = self.request.context.current_sphere_id
        try:
            # Validate the event exists in the manager's sphere (access guard).
            event = self.request.services.events.read_by_slug(sphere_id, slug)
        except NotFoundError:
            return JsonResponse({"error": "Event not found"}, status=404)

        try:
            data = json.loads(self.request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)
        if not isinstance(data, dict):
            return JsonResponse({"error": "Expected a JSON object"}, status=400)

        space_ids = data.get("space_ids")
        if not isinstance(space_ids, list) or not all(
            isinstance(pk, int) for pk in space_ids
        ):
            return JsonResponse({"error": "Invalid space_ids"}, status=400)

        parent_pk = data.get("parent_pk")  # null for the root level
        if parent_pk is not None and not isinstance(parent_pk, int):
            return JsonResponse({"error": "Invalid parent_pk"}, status=400)

        self.request.services.space_tree.reorder(
            parent_id=parent_pk, child_pks=space_ids, event_id=event.pk
        )
        return JsonResponse({"success": True})
