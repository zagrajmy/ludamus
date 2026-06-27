# pylint: disable=duplicate-code
"""Recursive Space-tree CRUD for the panel "Venues" section."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.chronology.panel.views.base import (
    EventContextMixin,
    PanelAccessMixin,
    PanelRequest,
)
from ludamus.gates.web.django.forms import SpaceForm, create_space_copy_form
from ludamus.pacts import NotFoundError

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.pacts.venues import SpaceNodeDTO


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

        context["active_nav"] = "venues"
        context["tree"] = self.request.services.space_tree.list_tree(current_event.pk)
        return TemplateResponse(self.request, "panel/spaces.html", context)


class SpaceCreatePageView(PanelAccessMixin, EventContextMixin, View):
    """Create a node, optionally under a parent (parent_pk in the URL)."""

    request: PanelRequest

    def _parent(
        self, current_event_pk: int, parent_pk: int | None
    ) -> SpaceNodeDTO | None:
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
                    name=form.cleaned_data["name"],
                    capacity=form.cleaned_data.get("capacity"),
                    description=form.cleaned_data.get("description") or "",
                )
            except ValidationError as exc:
                form.add_error(None, exc.messages[0])
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

    def _node(self, current_event_pk: int, pk: int) -> SpaceNodeDTO:
        node = self.request.services.space_tree.read(pk)
        if node.event_id != current_event_pk:
            raise NotFoundError
        return node

    def get(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")
        try:
            node = self._node(current_event.pk, pk)
        except NotFoundError:
            messages.error(self.request, _("Space not found."))
            return redirect("panel:venues", slug=slug)

        context["active_nav"] = "venues"
        context["parent"] = None
        context["node"] = node
        context["form"] = SpaceForm(
            initial={
                "name": node.name,
                "capacity": node.capacity,
                "description": node.description,
            }
        )
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

        form = SpaceForm(self.request.POST)
        if form.is_valid():
            try:
                self.request.services.space_tree.update(
                    pk=node.pk,
                    name=form.cleaned_data["name"],
                    capacity=form.cleaned_data.get("capacity"),
                    description=form.cleaned_data.get("description") or "",
                )
            except ValidationError as exc:
                form.add_error(None, exc.messages[0])
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
    ) -> tuple[SpaceNodeDTO, list[tuple[int, str]]]:
        node = self.request.services.space_tree.read(pk)
        if node.event_id != current_event_pk:
            raise NotFoundError
        choices = [
            (event.pk, event.name)
            for event in context["events"]
            if event.pk != current_event_pk
        ]
        return node, choices

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

        context["active_nav"] = "venues"
        context["node"] = node
        context["form"] = create_space_copy_form(choices)()
        return TemplateResponse(self.request, "panel/space-copy.html", context)

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
            context["active_nav"] = "venues"
            context["node"] = node
            context["form"] = form
            return TemplateResponse(self.request, "panel/space-copy.html", context)

        target_event_id = int(form.cleaned_data["target_event"])
        target_name = next(
            (e.name for e in context["events"] if e.pk == target_event_id), ""
        )
        self.request.services.space_tree.copy_to_event(
            pk=node.pk, target_event_id=target_event_id
        )
        messages.success(
            self.request,
            _("Space copied to %(event)s successfully.") % {"event": target_name},
        )
        return redirect("panel:venues", slug=slug)


class SpaceReorderActionView(PanelAccessMixin, View):
    """Reorder siblings under one parent (POST only, JSON)."""

    request: PanelRequest
    http_method_names = ("post",)

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        sphere_id = self.request.context.current_sphere_id
        try:
            # Validate the event exists in the manager's sphere (access guard).
            self.request.di.uow.events.read_by_slug(slug, sphere_id)
        except NotFoundError:
            return JsonResponse({"error": "Event not found"}, status=404)

        try:
            data = json.loads(self.request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        if (space_ids := data.get("space_ids")) is None:
            return JsonResponse({"error": "Missing space_ids"}, status=400)

        # parent_pk is null for the root level.
        self.request.services.space_tree.reorder(
            parent_id=data.get("parent_pk"), child_pks=space_ids
        )
        return JsonResponse({"success": True})
