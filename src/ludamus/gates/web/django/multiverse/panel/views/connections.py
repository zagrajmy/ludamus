"""Connection CRUD views for the sphere panel."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.multiverse.access import (
    MultiverseRequest,
    SphereAccessMixin,
)
from ludamus.gates.web.django.multiverse.panel.forms import ConnectionForm
from ludamus.gates.web.django.multiverse.panel.views.base import sphere_panel_context
from ludamus.pacts import NotFoundError, RedirectError

if TYPE_CHECKING:
    from django.http import HttpResponse


def _connection_not_found() -> RedirectError:
    return RedirectError(
        reverse("multiverse:panel:connections"), error=_("Connection not found.")
    )


class ConnectionsPageView(SphereAccessMixin, View):
    """List import connections for the current sphere."""

    request: MultiverseRequest

    def get(self, _request: MultiverseRequest) -> HttpResponse:
        sphere_id = self.request.context.current_sphere_id
        connections = self.request.services.connections.list_for_sphere(sphere_id)
        return TemplateResponse(
            self.request,
            "multiverse/panel/connections/list.html",
            {
                **sphere_panel_context(self.request, active_tab="connections"),
                "connections": connections,
            },
        )


class ConnectionCreatePageView(SphereAccessMixin, View):
    """Create a new import connection."""

    request: MultiverseRequest

    def get(self, _request: MultiverseRequest) -> HttpResponse:
        return TemplateResponse(
            self.request,
            "multiverse/panel/connections/create.html",
            {
                **sphere_panel_context(self.request, active_tab="connections"),
                "form": ConnectionForm(is_create=True),
            },
        )

    def post(self, _request: MultiverseRequest) -> HttpResponse:
        form = ConnectionForm(self.request.POST, is_create=True)
        if not form.is_valid():
            return TemplateResponse(
                self.request,
                "multiverse/panel/connections/create.html",
                {
                    **sphere_panel_context(self.request, active_tab="connections"),
                    "form": form,
                },
            )

        sphere_id = self.request.context.current_sphere_id
        plaintext = form.cleaned_data["secret"].encode("utf-8")
        self.request.services.connections.create(
            sphere_id, form.cleaned_data["display_name"], plaintext
        )
        messages.success(self.request, _("Connection created successfully."))
        return redirect("multiverse:panel:connections")


class ConnectionEditPageView(SphereAccessMixin, View):
    """Edit an existing import connection."""

    request: MultiverseRequest

    def get(self, _request: MultiverseRequest, pk: int) -> HttpResponse:
        sphere_id = self.request.context.current_sphere_id
        try:
            connection = self.request.services.connections.get(sphere_id, pk)
        except NotFoundError:
            raise _connection_not_found() from None

        form = ConnectionForm(initial={"display_name": connection.display_name})
        return TemplateResponse(
            self.request,
            "multiverse/panel/connections/edit.html",
            {
                **sphere_panel_context(self.request, active_tab="connections"),
                "form": form,
                "connection": connection,
            },
        )

    def post(self, _request: MultiverseRequest, pk: int) -> HttpResponse:
        sphere_id = self.request.context.current_sphere_id
        try:
            connection = self.request.services.connections.get(sphere_id, pk)
        except NotFoundError:
            raise _connection_not_found() from None

        form = ConnectionForm(self.request.POST)
        if not form.is_valid():
            return TemplateResponse(
                self.request,
                "multiverse/panel/connections/edit.html",
                {
                    **sphere_panel_context(self.request, active_tab="connections"),
                    "form": form,
                    "connection": connection,
                },
            )

        display_name = form.cleaned_data["display_name"]
        if form.cleaned_data["replace_secret"]:
            plaintext = form.cleaned_data["secret"].encode("utf-8")
            self.request.services.connections.update(
                sphere_id, pk, display_name, plaintext
            )
        else:
            self.request.services.connections.update(sphere_id, pk, display_name)
        messages.success(self.request, _("Connection updated successfully."))
        return redirect("multiverse:panel:connections")


class ConnectionDeletePageView(SphereAccessMixin, View):
    """Confirm-and-delete page for a connection."""

    request: MultiverseRequest

    def get(self, _request: MultiverseRequest, pk: int) -> HttpResponse:
        sphere_id = self.request.context.current_sphere_id
        try:
            connection = self.request.services.connections.get(sphere_id, pk)
        except NotFoundError:
            raise _connection_not_found() from None

        return TemplateResponse(
            self.request,
            "multiverse/panel/connections/delete.html",
            {
                **sphere_panel_context(self.request, active_tab="connections"),
                "connection": connection,
            },
        )

    def post(self, _request: MultiverseRequest, pk: int) -> HttpResponse:
        sphere_id = self.request.context.current_sphere_id
        try:
            self.request.services.connections.delete(sphere_id, pk)
        except NotFoundError:
            raise _connection_not_found() from None

        messages.success(self.request, _("Connection deleted successfully."))
        return redirect("multiverse:panel:connections")
