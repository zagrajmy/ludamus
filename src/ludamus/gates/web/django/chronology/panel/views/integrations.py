"""Event integration CRUD + check views (event panel)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Protocol

from django.contrib import messages
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.chronology.panel.forms import (
    EventIntegrationForm,
    IntegrationFormContext,
    integration_signature,
)
from ludamus.gates.web.django.chronology.panel.views.base import (
    EventContextMixin,
    PanelAccessMixin,
    PanelRequest,
)
from ludamus.pacts import NotFoundError
from ludamus.pacts.chronology import (
    CheckOutcome,
    EventIntegrationCreateData,
    EventIntegrationUpdateData,
    IntegrationCheckRequest,
    IntegrationImplementationId,
    IntegrationKind,
)

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.pacts import EventDTO
    from ludamus.pacts.chronology import EventIntegrationDTO


class _PanelViewLike(Protocol):
    request: PanelRequest

    def get_event_context(
        self, slug: str
    ) -> tuple[dict[str, Any], EventDTO | None]: ...


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


def _load_integration(
    view: _PanelViewLike, slug: str, pk: int
) -> (
    tuple[dict[str, Any], EventDTO, EventIntegrationDTO]
    | tuple[None, None, HttpResponse]
):
    # On miss returns (None, None, redirect_response) — caller returns the
    # third element as-is; otherwise (context, event, integration).
    context, current_event = view.get_event_context(slug)
    if current_event is None:
        return None, None, redirect("panel:index")
    try:
        integration = view.request.services.event_integrations.get(current_event.pk, pk)
    except NotFoundError:
        messages.error(view.request, _("Integration not found."))
        return None, None, redirect("panel:event-integration-settings", slug=slug)
    return context, current_event, integration


class IntegrationCreatePageView(PanelAccessMixin, EventContextMixin, View):
    """Create a new event integration; kind is derived from the picked impl."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")
        form = EventIntegrationForm(**_form_kwargs(self.request, current_event.pk))
        context["active_nav"] = "settings"
        context["form"] = form
        return TemplateResponse(
            self.request, "chronology/panel/integrations/create.html", context
        )

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        form = EventIntegrationForm(
            self.request.POST, **_form_kwargs(self.request, current_event.pk)
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
            event_id=current_event.pk,
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


class IntegrationEditPageView(PanelAccessMixin, EventContextMixin, View):
    """Edit an existing event integration."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
        loaded = _load_integration(self, slug, pk)
        if loaded[1] is None:
            return loaded[2]
        context, current_event, integration = loaded

        form = EventIntegrationForm(
            initial={
                "display_name": integration.display_name,
                "implementation": integration.implementation,
                "connection": str(integration.connection_id),
                "config_json": integration.config_json,
            },
            **_form_kwargs(self.request, current_event.pk, existing=integration),
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
        loaded = _load_integration(self, slug, pk)
        if loaded[1] is None:
            return loaded[2]
        context, current_event, integration = loaded

        form = EventIntegrationForm(
            self.request.POST,
            initial={"implementation": integration.implementation},
            **_form_kwargs(self.request, current_event.pk, existing=integration),
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
            event_id=current_event.pk,
            pk=pk,
            data=EventIntegrationUpdateData(
                display_name=form.cleaned_data["display_name"],
                connection_id=int(form.cleaned_data["connection"]),
                config_json=form.cleaned_data["config_json"],
            ),
        )
        messages.success(self.request, _("Integration updated."))
        return redirect("panel:event-integration-settings", slug=slug)


class IntegrationDeletePageView(PanelAccessMixin, EventContextMixin, View):
    """Confirm-and-delete page for an event integration."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
        loaded = _load_integration(self, slug, pk)
        if loaded[1] is None:
            return loaded[2]
        context, _current_event, integration = loaded
        context["active_nav"] = "settings"
        context["integration"] = integration
        return TemplateResponse(
            self.request, "chronology/panel/integrations/delete.html", context
        )

    def post(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
        loaded = _load_integration(self, slug, pk)
        if loaded[1] is None:
            return loaded[2]
        _ctx, current_event, _integration = loaded
        self.request.services.event_integrations.delete(current_event.pk, pk)
        messages.success(self.request, _("Integration deleted."))
        return redirect("panel:event-integration-settings", slug=slug)


class IntegrationCheckActionView(PanelAccessMixin, EventContextMixin, View):
    """POST-only HTMX endpoint that runs `Check integration`.

    Returns the outcome partial as the response body.
    """

    request: PanelRequest

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        _ctx, current_event = self.get_event_context(slug)
        if current_event is None:
            return HttpResponseBadRequest("Unknown event")

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
