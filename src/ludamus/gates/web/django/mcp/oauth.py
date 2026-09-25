"""OAuth 2.1 authorization server for MCP clients, keyed by CIMD client ids.

Any MCP client that publishes a Client ID Metadata Document can connect: the
user signs in, approves the client on the consent page, and the token endpoint
hands back the same signed Bearer token `/mcp/token/` mints by hand. The
resource the client asks for picks the tier; the organizer tier also asks the
user which event the token may write.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlencode, urlsplit, urlunsplit

from django import forms
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, JsonResponse
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from ludamus.gates.web.django.mcp.tokens import (
    TOKEN_MAX_AGE_DAYS,
    mint_organizer_token,
    mint_token,
)
from ludamus.pacts.legacy import NotFoundError
from ludamus.pacts.mcp import McpClientRejectedError, McpGrantRejectedError, ToolScope
from ludamus.pacts.multiverse import SphereRole

if TYPE_CHECKING:
    from django.http import QueryDict

    from ludamus.gates.web.django.entities import AuthenticatedRootRequest, RootRequest
    from ludamus.pacts.mcp import McpClientDTO, McpGrantDTO

logger = logging.getLogger(__name__)

TEMPLATE = "mcp/authorize.html"

_ENDPOINT_URL_NAMES = {
    ToolScope.MAINTAINER: "mcp:endpoint",
    ToolScope.ORGANIZER: "mcp:organizer-endpoint",
}
_METADATA_URL_NAMES = {
    ToolScope.MAINTAINER: "oauth-protected-resource-maintainer",
    ToolScope.ORGANIZER: "oauth-protected-resource-organizer",
}


def issuer(request: RootRequest) -> str:
    return f"{request.scheme}://{request.get_host()}"


def resource_metadata_url(request: RootRequest, scope: ToolScope) -> str:
    return request.build_absolute_uri(reverse(_METADATA_URL_NAMES[scope]))


def _resource_url(request: RootRequest, scope: ToolScope) -> str:
    return request.build_absolute_uri(reverse(_ENDPOINT_URL_NAMES[scope]))


def _scope_for_resource(request: RootRequest, resource: str) -> ToolScope | None:
    for scope in ToolScope:
        if resource.rstrip("/") == _resource_url(request, scope).rstrip("/"):
            return scope
    return None


@require_GET
def protected_resource_metadata(request: RootRequest, scope: str) -> JsonResponse:
    """RFC 9728: tells a client which authorization server guards the endpoint."""
    return JsonResponse(
        {
            "resource": _resource_url(request, ToolScope(scope)),
            "authorization_servers": [issuer(request)],
            "bearer_methods_supported": ["header"],
            "resource_name": f"Zagrajmy MCP ({scope})",
        }
    )


@require_GET
def authorization_server_metadata(request: RootRequest) -> JsonResponse:
    """RFC 8414, advertising CIMD instead of dynamic client registration."""
    return JsonResponse(
        {
            "issuer": issuer(request),
            "authorization_endpoint": request.build_absolute_uri(
                reverse("mcp:oauth-authorize")
            ),
            "token_endpoint": request.build_absolute_uri(reverse("mcp:oauth-token")),
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "client_id_metadata_document_supported": True,
            "authorization_response_iss_parameter_supported": True,
        }
    )


@dataclass(frozen=True, slots=True)
class _Authorization:
    client: McpClientDTO
    scope: ToolScope
    code_challenge: str
    state: str | None


class McpConsentForm(forms.Form):
    def __init__(
        self, data: QueryDict | None = None, *, events: list[tuple[str, str]]
    ) -> None:
        super().__init__(data)
        self.fields["event"] = forms.ChoiceField(label=_("Event"), choices=events)


@method_decorator(never_cache, name="dispatch")
class McpAuthorizeView(LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    def get(self, request: AuthenticatedRootRequest) -> HttpResponse:
        authorization = self._begin(request.GET)
        if isinstance(authorization, HttpResponse):
            return authorization
        return self._consent(authorization)

    def post(self, request: AuthenticatedRootRequest) -> HttpResponse:
        authorization = self._begin(request.POST)
        if isinstance(authorization, HttpResponse):
            return authorization
        if request.POST.get("decision") != "approve":
            logger.info(
                "MCP OAuth consent denied: user=%s client=%s",
                request.context.current_user_id,
                authorization.client.client_id,
            )
            return _redirect_error(
                authorization,
                error="access_denied",
                description="The user denied access.",
                issuer_url=issuer(request),
            )
        if not self._may_grant(authorization.scope):
            return self._consent(authorization)
        sphere_id = event_id = None
        if authorization.scope is ToolScope.ORGANIZER:
            form = McpConsentForm(request.POST, events=self._events())
            if not form.is_valid():
                return self._consent(authorization, form=form)
            sphere_id = request.context.current_sphere_id
            try:
                event_id = request.services.events.read_by_slug(
                    sphere_id, form.cleaned_data["event"]
                ).pk
            except NotFoundError:
                form.add_error("event", _("This event is not in this sphere."))
                return self._consent(authorization, form=form)
        code = request.services.mcp_authorization.issue_code(
            {
                "client_id": authorization.client.client_id,
                "redirect_uri": authorization.client.redirect_uri,
                "code_challenge": authorization.code_challenge,
                "user_id": request.context.current_user_id,
                "scope": authorization.scope,
                "sphere_id": sphere_id,
                "event_id": event_id,
            }
        )
        logger.info(
            "MCP OAuth consent granted: user=%s client=%s scope=%s event=%s",
            request.context.current_user_id,
            authorization.client.client_id,
            authorization.scope,
            event_id,
        )
        return _redirect(authorization, params={"code": code, "iss": issuer(request)})

    def _begin(self, params: QueryDict) -> _Authorization | HttpResponse:
        try:
            client = self.request.services.mcp_authorization.resolve_client(
                client_id=params.get("client_id", ""),
                redirect_uri=params.get("redirect_uri", ""),
            )
        except McpClientRejectedError as exc:
            # Without a verified redirect_uri there is nowhere safe to send
            # the error, so the user reads it here.
            logger.info(
                "MCP OAuth client rejected: client=%s reason=%s",
                params.get("client_id", ""),
                exc,
            )
            return TemplateResponse(
                self.request, TEMPLATE, {"client_error": str(exc)}, status=400
            )
        state = params.get("state")
        scope = _scope_for_resource(self.request, params.get("resource", ""))
        partial = _Authorization(
            client=client,
            scope=scope or ToolScope.MAINTAINER,
            code_challenge=params.get("code_challenge", ""),
            state=state,
        )
        if params.get("response_type") != "code":
            return _redirect_error(
                partial,
                error="unsupported_response_type",
                description="Only response_type=code is supported.",
                issuer_url=issuer(self.request),
            )
        if params.get("code_challenge_method") != "S256" or not partial.code_challenge:
            return _redirect_error(
                partial,
                error="invalid_request",
                description="PKCE with code_challenge_method=S256 is required.",
                issuer_url=issuer(self.request),
            )
        if scope is None:
            return _redirect_error(
                partial,
                error="invalid_target",
                description="The resource must be this site's /mcp/ endpoint.",
                issuer_url=issuer(self.request),
            )
        return partial

    def _may_grant(self, scope: ToolScope) -> bool:
        if self.request.user.is_superuser:
            return True
        if scope is ToolScope.MAINTAINER:
            return False
        # Organizer tools write, so a comms member's read-only role isn't enough.
        role = self.request.services.sphere_panel.manager_role(
            self.request.context.current_sphere_id,
            self.request.context.current_user_slug,
        )
        return role is SphereRole.MANAGER

    def _events(self) -> list[tuple[str, str]]:
        events = self.request.services.events.list_for_sphere(
            self.request.context.current_sphere_id, include_unpublished=True
        )
        # The first choice is the default, so lead with what's coming up
        # soonest and push past events to the end, newest first.
        events.sort(
            key=lambda event: (
                event.is_ended,
                (-1 if event.is_ended else 1) * event.start_time.timestamp(),
            )
        )
        return [(event.slug, event.name) for event in events]

    def _consent(
        self, authorization: _Authorization, *, form: McpConsentForm | None = None
    ) -> TemplateResponse:
        may_grant = self._may_grant(authorization.scope)
        wants_event = may_grant and authorization.scope is ToolScope.ORGANIZER
        events = self._events() if wants_event else []
        if events and form is None:
            form = McpConsentForm(events=events)
        return TemplateResponse(
            self.request,
            TEMPLATE,
            {
                "client_error": None,
                "client": authorization.client,
                "scope": authorization.scope.value,
                "may_grant": may_grant,
                "wants_event": wants_event,
                "form": form if events else None,
                "can_approve": may_grant and (not wants_event or bool(events)),
                "params": {
                    "response_type": "code",
                    "client_id": authorization.client.client_id,
                    "redirect_uri": authorization.client.redirect_uri,
                    "code_challenge": authorization.code_challenge,
                    "code_challenge_method": "S256",
                    "state": authorization.state or "",
                    "resource": _resource_url(self.request, authorization.scope),
                },
                "token_max_age_days": TOKEN_MAX_AGE_DAYS,
            },
            status=200 if may_grant else 403,
        )


class _ClientRedirect(HttpResponse):
    """A 302 to a redirect_uri the client's own metadata document lists.

    HttpResponseRedirect refuses the custom schemes native clients register
    (cursor://, vscode://); the mill already vetted this URI.
    """

    status_code = 302

    def __init__(self, location: str) -> None:
        super().__init__()
        self["Location"] = location

    @property
    def url(self) -> str:
        return self["Location"]


def _redirect(authorization: _Authorization, *, params: dict[str, str]) -> HttpResponse:
    if authorization.state is not None:
        params["state"] = authorization.state
    parts = urlsplit(authorization.client.redirect_uri)
    query = f"{parts.query}&{urlencode(params)}" if parts.query else urlencode(params)
    return _ClientRedirect(urlunsplit(parts._replace(query=query)))


def _redirect_error(
    authorization: _Authorization, *, error: str, description: str, issuer_url: str
) -> HttpResponse:
    return _redirect(
        authorization,
        params={"error": error, "error_description": description, "iss": issuer_url},
    )


@method_decorator(csrf_exempt, name="dispatch")
class McpTokenView(View):
    """Code-for-token exchange; public clients prove themselves with PKCE."""

    request: RootRequest

    @staticmethod
    def post(request: RootRequest) -> JsonResponse:
        if request.POST.get("grant_type") != "authorization_code":
            return _token_error(
                "unsupported_grant_type", "Only authorization_code is supported."
            )
        try:
            grant = request.services.mcp_authorization.redeem_code(
                code=request.POST.get("code", ""),
                client_id=request.POST.get("client_id", ""),
                redirect_uri=request.POST.get("redirect_uri", ""),
                code_verifier=request.POST.get("code_verifier", ""),
            )
            access_token = _mint(grant)
        except McpGrantRejectedError as exc:
            logger.info(
                "MCP OAuth token refused: client=%s reason=%s",
                request.POST.get("client_id", ""),
                exc,
            )
            return _token_error("invalid_grant", str(exc))
        logger.info(
            "MCP OAuth token issued: user=%s client=%s scope=%s",
            grant.user_id,
            grant.client_id,
            grant.scope,
        )
        response = JsonResponse(
            {
                "access_token": access_token,
                "token_type": "Bearer",
                "expires_in": TOKEN_MAX_AGE_DAYS * 24 * 60 * 60,
            }
        )
        response["Cache-Control"] = "no-store"
        return response


def _mint(grant: McpGrantDTO) -> str:
    if grant.scope is ToolScope.MAINTAINER:
        return mint_token(grant.user_id)
    if grant.sphere_id is None or grant.event_id is None:
        msg = "The organizer grant names no event."
        raise McpGrantRejectedError(msg)
    return mint_organizer_token(
        user_id=grant.user_id, sphere_id=grant.sphere_id, event_id=grant.event_id
    )


def _token_error(error: str, description: str) -> JsonResponse:
    response = JsonResponse(
        {"error": error, "error_description": description}, status=400
    )
    response["Cache-Control"] = "no-store"
    return response
