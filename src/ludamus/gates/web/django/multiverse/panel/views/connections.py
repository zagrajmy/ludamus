"""Connection CRUD views for the sphere panel."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.generic.base import View

from ludamus.gates.web.django.multiverse.access import (
    MultiverseRequest,
    SphereAccessMixin,
)
from ludamus.gates.web.django.multiverse.panel.forms import ConnectionForm
from ludamus.gates.web.django.multiverse.panel.views.base import sphere_panel_context
from ludamus.pacts import NotFoundError, RedirectError
from ludamus.pacts.multiverse import (
    ConnectionCheckStatus,
    ConnectionProvider,
    ConnectionWriteDict,
    CredentialAuthError,
    DuplicateConnectionDisplayNameError,
)

if TYPE_CHECKING:
    from django.http import HttpResponse
    from django.utils.functional import _StrPromise

    from ludamus.pacts.multiverse import ConnectionDTO


_CREDENTIAL_ERROR_TEMPLATES: dict[ConnectionCheckStatus, _StrPromise] = {
    ConnectionCheckStatus.AUTH_FAILED: gettext_lazy(
        "Credential authentication failed: %(detail)s"
    ),
    ConnectionCheckStatus.NETWORK_ERROR: gettext_lazy(
        "Could not reach the provider to verify credentials: %(detail)s"
    ),
}


def _credential_error_message(exc: CredentialAuthError) -> str:
    template = _CREDENTIAL_ERROR_TEMPLATES[exc.status]
    return str(template % {"detail": exc.detail})


def _connection_not_found() -> RedirectError:
    return RedirectError(
        reverse("multiverse:panel:connections"), error=_("Connection not found.")
    )


def _add_duplicate_display_name_error(form: ConnectionForm) -> None:
    form.add_error(
        "display_name",
        _("A connection with this display name already exists."),
    )


def _create_response(request: MultiverseRequest, form: ConnectionForm) -> TemplateResponse:
    return TemplateResponse(
        request,
        "multiverse/panel/connections/create.html",
        {
            **sphere_panel_context(request, active_tab="connections"),
            "form": form,
        },
    )


def _edit_response(
    request: MultiverseRequest, form: ConnectionForm, connection: ConnectionDTO
) -> TemplateResponse:
    return TemplateResponse(
        request,
        "multiverse/panel/connections/edit.html",
        {
            **sphere_panel_context(request, active_tab="connections"),
            "form": form,
            "connection": connection,
        },
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
            return _create_response(self.request, form)

        sphere_id = self.request.context.current_sphere_id
        data: ConnectionWriteDict = {
            "service": ConnectionProvider(form.cleaned_data["service"]),
            "display_name": form.cleaned_data["display_name"],
        }
        plaintext = form.cleaned_data["credentials"].encode("utf-8")
        try:
            self.request.services.connections.create(sphere_id, data, plaintext)
        except CredentialAuthError as exc:
            form.add_error(None, _credential_error_message(exc))
            return _create_response(self.request, form)
        except DuplicateConnectionDisplayNameError:
            _add_duplicate_display_name_error(form)
            return _create_response(self.request, form)
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

        form = ConnectionForm(
            initial={
                "service": connection.service.value,
                "display_name": connection.display_name,
            }
        )
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
            return _edit_response(self.request, form, connection)

        data: ConnectionWriteDict = {
            "service": ConnectionProvider(form.cleaned_data["service"]),
            "display_name": form.cleaned_data["display_name"],
        }
        if form.cleaned_data["replace_credentials"]:
            plaintext = form.cleaned_data["credentials"].encode("utf-8")
            try:
                self.request.services.connections.update(sphere_id, pk, data, plaintext)
            except CredentialAuthError as exc:
                form.add_error(None, _credential_error_message(exc))
                return _edit_response(self.request, form, connection)
            except DuplicateConnectionDisplayNameError:
                _add_duplicate_display_name_error(form)
                return _edit_response(self.request, form, connection)
        else:
            try:
                self.request.services.connections.update(sphere_id, pk, data)
            except DuplicateConnectionDisplayNameError:
                _add_duplicate_display_name_error(form)
                return _edit_response(self.request, form, connection)
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
