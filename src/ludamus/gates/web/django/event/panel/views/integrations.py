"""Event integration CRUD + check views (event panel)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from django.contrib import messages
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.event.panel.forms import (
    EventIntegrationForm,
    IntegrationFormContext,
    integration_signature,
)
from ludamus.gates.web.django.event.panel.views.base import EventPanelMixin
from ludamus.gates.web.django.redirects import RedirectError
from ludamus.pacts.chronology import (
    CheckOutcome,
    EventIntegrationCreateData,
    EventIntegrationUpdateData,
    IntegrationCheckRequest,
    IntegrationImplementationId,
    IntegrationKind,
)
from ludamus.pacts.errors import NotFoundError

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.gates.web.django.panel import PanelRequest
    from ludamus.pacts.chronology import EventIntegrationDTO


def _form_kwargs(
    request: PanelRequest, event_id: int, *, existing: EventIntegrationDTO | None = None
) -> dict[str, Any]:
    sphere_id = request.context.current_sphere_id
    integrations_service = request.services.event_integrations
    if existing is not None:
        implementations = integrations_service.list_implementations(existing.kind)
        locked_kind: IntegrationKind | None = existing.kind
        exclude_pk: int | None = existing.pk
        initial_connection_id: int | None = existing.connection_id
        initial_config_json: str | None = existing.config_json
    else:
        implementations = integrations_service.list_all_implementations()
        locked_kind = None
        exclude_pk = None
        initial_connection_id = None
        initial_config_json = None

    taken_by_kind: dict[IntegrationKind, set[str]] = {}
    for integration in integrations_service.list_for_event(event_id):
        if integration.pk == exclude_pk:
            continue
        taken_by_kind.setdefault(integration.kind, set()).add(integration.display_name)
    return {
        "implementations": implementations,
        "connections": request.services.connections.list_for_sphere(sphere_id),
        "context": IntegrationFormContext(
            taken_display_names_by_kind=taken_by_kind,
            locked_kind=locked_kind,
            initial_connection_id=initial_connection_id,
            initial_config_json=initial_config_json,
        ),
    }


class _IntegrationView(EventPanelMixin, View):
    request: PanelRequest

    def _integration(self, slug: str, pk: int) -> EventIntegrationDTO:
        try:
            return self.request.services.event_integrations.get(
                self.current_event.pk, pk
            )
        except NotFoundError:
            raise RedirectError(
                reverse("panel:event-integration-settings", kwargs={"slug": slug}),
                error=_("Integration not found."),
            ) from None


class IntegrationCreatePageView(EventPanelMixin, View):
    """Create a new event integration; kind is derived from the picked impl."""

    request: PanelRequest

    def get(self, _request: PanelRequest, **_kwargs: str) -> HttpResponse:
        context = self.panel_context()
        form = EventIntegrationForm(**_form_kwargs(self.request, self.current_event.pk))
        context["active_nav"] = "settings"
        context["form"] = form
        return TemplateResponse(
            self.request, "chronology/panel/integrations/create.html", context
        )

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context = self.panel_context()

        form = EventIntegrationForm(
            self.request.POST, **_form_kwargs(self.request, self.current_event.pk)
        )
        if not form.is_valid():
            context["active_nav"] = "settings"
            context["form"] = form
            return TemplateResponse(
                self.request, "chronology/panel/integrations/create.html", context
            )

        sphere_id = self.request.context.current_sphere_id
        implementation = form.cleaned_data["implementation"]
        integrations_service = self.request.services.event_integrations
        # A valid form guarantees the implementation is registered; derive its
        # kind from the same registry the form validated against.
        resolved_kind = integrations_service.list_all_implementations()[
            implementation
        ].kind
        integrations_service.create(
            sphere_id=sphere_id,
            event_id=self.current_event.pk,
            data=EventIntegrationCreateData(
                kind=resolved_kind,
                implementation=implementation,
                connection_id=int(form.cleaned_data["connection"]),
                display_name=form.cleaned_data["display_name"],
                config_json=form.cleaned_data["config_json"],
            ),
        )
        messages.success(self.request, _("Integration created."))
        return redirect("panel:event-integration-settings", slug=slug)


class IntegrationEditPageView(_IntegrationView):
    """Edit an existing event integration."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
        context = self.panel_context()
        integration = self._integration(slug, pk)

        form = EventIntegrationForm(
            initial={
                "display_name": integration.display_name,
                "implementation": integration.implementation,
                "connection": str(integration.connection_id),
                "config_json": integration.config_json,
            },
            **_form_kwargs(self.request, self.current_event.pk, existing=integration),
        )
        # Lock implementation on edit — kind+impl pair is structural.
        form.fields["implementation"].disabled = True
        context["active_nav"] = "settings"
        context["form"] = form
        context["integration"] = integration
        return TemplateResponse(
            self.request, "chronology/panel/integrations/edit.html", context
        )

    def post(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
        context = self.panel_context()
        integration = self._integration(slug, pk)

        form = EventIntegrationForm(
            self.request.POST,
            initial={"implementation": integration.implementation},
            **_form_kwargs(self.request, self.current_event.pk, existing=integration),
        )
        form.fields["implementation"].disabled = True
        if not form.is_valid():
            context["active_nav"] = "settings"
            context["form"] = form
            context["integration"] = integration
            return TemplateResponse(
                self.request, "chronology/panel/integrations/edit.html", context
            )

        sphere_id = self.request.context.current_sphere_id
        self.request.services.event_integrations.update(
            sphere_id=sphere_id,
            event_id=self.current_event.pk,
            pk=pk,
            data=EventIntegrationUpdateData(
                display_name=form.cleaned_data["display_name"],
                connection_id=int(form.cleaned_data["connection"]),
                config_json=form.cleaned_data["config_json"],
            ),
        )
        messages.success(self.request, _("Integration updated."))
        return redirect("panel:event-integration-settings", slug=slug)


class IntegrationDeletePageView(_IntegrationView):
    """Confirm-and-delete page for an event integration."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
        context = self.panel_context()
        integration = self._integration(slug, pk)
        context["active_nav"] = "settings"
        context["integration"] = integration
        return TemplateResponse(
            self.request, "chronology/panel/integrations/delete.html", context
        )

    def post(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
        self._integration(slug, pk)
        self.request.services.event_integrations.delete(self.current_event.pk, pk)
        messages.success(self.request, _("Integration deleted."))
        return redirect("panel:event-integration-settings", slug=slug)


class IntegrationCheckActionView(EventPanelMixin, View):
    """POST-only HTMX endpoint that runs `Check integration`.

    Returns the outcome partial as the response body.
    """

    request: PanelRequest

    def event_not_found(self) -> HttpResponse:
        # An HTMX fragment: a redirect would swap the panel index into it.
        messages.error(self.request, _("Event not found."))
        return HttpResponseBadRequest("Unknown event")

    def post(self, _request: PanelRequest, **_kwargs: str) -> HttpResponse:
        implementation_raw = (self.request.POST.get("implementation") or "").strip()
        connection_raw = (self.request.POST.get("connection") or "").strip()
        config_raw = self.request.POST.get("config_json") or "{}"

        if not implementation_raw or not connection_raw:
            return TemplateResponse(
                self.request,
                "chronology/panel/integrations/_check_result.html",
                {
                    "passed": False,
                    "hint": _(
                        "Pick an implementation and a connection before "
                        "running the check."
                    ),
                    "signature": "",
                },
            )

        try:
            implementation = IntegrationImplementationId(implementation_raw)
        except ValueError:
            return TemplateResponse(
                self.request,
                "chronology/panel/integrations/_check_result.html",
                {
                    "passed": False,
                    "hint": (
                        _("Unknown implementation: %(id)s") % {"id": implementation_raw}
                    ),
                    "signature": "",
                },
            )

        try:
            connection_id = int(connection_raw)
        except ValueError:
            return HttpResponseBadRequest("Bad connection id")

        try:
            parsed_config = json.loads(config_raw)
        except json.JSONDecodeError as exc:
            return TemplateResponse(
                self.request,
                "chronology/panel/integrations/_check_result.html",
                {"passed": False, "hint": str(exc), "signature": ""},
            )
        if not isinstance(parsed_config, dict):
            return TemplateResponse(
                self.request,
                "chronology/panel/integrations/_check_result.html",
                {
                    "passed": False,
                    "hint": _("Configuration must be a JSON object."),
                    "signature": "",
                },
            )

        sphere_id = self.request.context.current_sphere_id
        result = self.request.services.event_integrations.check(
            IntegrationCheckRequest(
                sphere_id=sphere_id,
                implementation=implementation,
                connection_id=connection_id,
                config_json=config_raw,
            )
        )
        passed = result.outcome == CheckOutcome.OK
        signature = integration_signature(connection_id, config_raw) if passed else ""
        return TemplateResponse(
            self.request,
            "chronology/panel/integrations/_check_result.html",
            {"passed": passed, "hint": result.hint, "signature": signature},
        )
