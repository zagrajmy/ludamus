"""OAuth 2.1 authorization server for MCP clients, keyed by CIMD client ids.

Any MCP client that publishes a Client ID Metadata Document can connect: the
user signs in, approves the client on the consent page, and the token endpoint
hands back the same signed Bearer token `/mcp/token/` mints by hand. The
rules live in `McpAuthorizationService`; this module maps HTTP onto it.
"""

from __future__ import annotations

import logging
import secrets
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
from ludamus.pacts.mcp import (
    ClientRejection,
    MaintainerGrant,
    McpAuthorizationRejectedError,
    McpClientRejectedError,
    McpGrantRejectedError,
    McpPendingAuthorizationDTO,
    OrganizerGrant,
    ToolScope,
)

if TYPE_CHECKING:
    from django.http import QueryDict
    from django.utils.functional import _StrPromise

    from ludamus.gates.web.django.entities import AuthenticatedRootRequest, RootRequest
    from ludamus.pacts.mcp import (
        McpAuthorizationRequest,
        McpConsentDTO,
        McpEventChoiceDTO,
        McpGrant,
    )

logger = logging.getLogger(__name__)

TEMPLATE = "mcp/authorize.html"
# One slot: a new consent page replaces an abandoned one, and the id pins the
# decision to the page the user actually saw.
PENDING_SESSION_KEY = "mcp_oauth_pending"

_ENDPOINT_URL_NAMES = {
    ToolScope.MAINTAINER: "mcp:endpoint",
    ToolScope.ORGANIZER: "mcp:organizer-endpoint",
}
_METADATA_URL_NAMES = {
    ToolScope.MAINTAINER: "oauth-protected-resource-maintainer",
    ToolScope.ORGANIZER: "oauth-protected-resource-organizer",
}
_CLIENT_REJECTIONS: dict[ClientRejection, _StrPromise] = {
    ClientRejection.BAD_CLIENT_ID: _(
        "The client did not identify itself with a metadata document URL."
    ),
    ClientRejection.UNREACHABLE: _(
        "The client's metadata document could not be fetched."
    ),
    ClientRejection.NOT_PUBLIC: _(
        "The client's metadata document is not on a public address."
    ),
    ClientRejection.INVALID_DOCUMENT: _("The client's metadata document is not valid."),
    ClientRejection.CLIENT_ID_MISMATCH: _(
        "The client's metadata document describes a different client."
    ),
    ClientRejection.CONFIDENTIAL_CLIENT: _(
        "Only public clients can connect, and this one expects a secret."
    ),
    ClientRejection.NO_REDIRECT_URIS: _(
        "The client's metadata document lists no redirect addresses."
    ),
    ClientRejection.BAD_REDIRECT_URI: _(
        "The client asked to return to an address that can't be used."
    ),
    ClientRejection.REDIRECT_NOT_LISTED: _(
        "The client asked to return to an address its metadata doesn't list."
    ),
}
_EXPIRED = _("This connection request expired. Start again from your client.")


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
def protected_resource_metadata(request: RootRequest, scope: ToolScope) -> JsonResponse:
    """RFC 9728: tells a client which authorization server guards the endpoint."""
    return JsonResponse(
        {
            "resource": _resource_url(request, scope),
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


class McpConsentForm(forms.Form):
    def __init__(
        self, data: QueryDict | None = None, *, events: list[McpEventChoiceDTO]
    ) -> None:
        super().__init__(data)
        self.fields["event"] = forms.TypedChoiceField(
            label=_("Event"),
            coerce=int,
            choices=[(event.pk, event.name) for event in events],
        )


@method_decorator(never_cache, name="dispatch")
class McpAuthorizeView(LoginRequiredMixin, View):
    """GET vets the request and asks; POST carries out the user's decision.

    The vetted request waits in the session between the two, so the POST
    neither refetches the client's metadata nor trusts echoed form fields.
    """

    request: AuthenticatedRootRequest

    def get(self, request: AuthenticatedRootRequest) -> HttpResponse:
        try:
            pending = request.services.mcp_authorization.begin(
                _authorization_request(request)
            )
        except McpClientRejectedError as exc:
            return self._client_error(exc.reason)
        except McpAuthorizationRejectedError as exc:
            return _reject(request, exc)
        pending_id = secrets.token_urlsafe(16)
        request.session[PENDING_SESSION_KEY] = {
            "id": pending_id,
            "pending": pending.model_dump(mode="json"),
        }
        return self._consent(pending, pending_id=pending_id)

    def post(self, request: AuthenticatedRootRequest) -> HttpResponse:
        pending_id = request.POST.get("pending", "")
        slot = request.session.pop(PENDING_SESSION_KEY, None)
        if not slot or slot.get("id") != pending_id:
            return TemplateResponse(
                request, TEMPLATE, {"client_error": _EXPIRED}, status=400
            )
        pending = McpPendingAuthorizationDTO.model_validate(slot["pending"])
        if request.POST.get("decision") != "approve":
            logger.info(
                "MCP OAuth consent denied: user=%s client=%s",
                request.context.current_user_id,
                pending.client.client_id,
            )
            return _redirect(
                request,
                redirect_uri=pending.client.redirect_uri,
                state=pending.state,
                error="access_denied",
                error_description="The user denied access.",
            )
        event_id = None
        consent = self._read_consent(pending)
        if consent.events:
            form = McpConsentForm(request.POST, events=consent.events)
            if not form.is_valid():
                request.session[PENDING_SESSION_KEY] = slot
                return self._render(pending, pending_id, consent=consent, form=form)
            event_id = form.cleaned_data["event"]
        try:
            code = request.services.mcp_authorization.approve(
                pending,
                user_id=request.context.current_user_id,
                user_slug=request.context.current_user_slug,
                sphere_id=request.context.current_sphere_id,
                event_id=event_id,
            )
        except McpAuthorizationRejectedError as exc:
            return _reject(request, exc)
        logger.info(
            "MCP OAuth consent granted: user=%s client=%s scope=%s event=%s",
            request.context.current_user_id,
            pending.client.client_id,
            pending.scope,
            event_id,
        )
        return _redirect(
            request,
            redirect_uri=pending.client.redirect_uri,
            state=pending.state,
            code=code,
        )

    def _read_consent(self, pending: McpPendingAuthorizationDTO) -> McpConsentDTO:
        return self.request.services.mcp_authorization.consent(
            pending,
            sphere_id=self.request.context.current_sphere_id,
            user_slug=self.request.context.current_user_slug,
        )

    def _consent(
        self, pending: McpPendingAuthorizationDTO, *, pending_id: str
    ) -> TemplateResponse:
        consent = self._read_consent(pending)
        form = McpConsentForm(events=consent.events) if consent.events else None
        return self._render(pending, pending_id, consent=consent, form=form)

    def _render(
        self,
        pending: McpPendingAuthorizationDTO,
        pending_id: str,
        *,
        consent: McpConsentDTO,
        form: McpConsentForm | None,
    ) -> TemplateResponse:
        wants_event = consent.may_grant and pending.scope is ToolScope.ORGANIZER
        return TemplateResponse(
            self.request,
            TEMPLATE,
            {
                "client_error": None,
                "client": pending.client,
                "scope": pending.scope.value,
                "may_grant": consent.may_grant,
                "wants_event": wants_event,
                "form": form,
                "can_approve": (
                    consent.may_grant and (not wants_event or form is not None)
                ),
                "pending": pending_id,
                "token_max_age_days": TOKEN_MAX_AGE_DAYS,
            },
            status=200 if consent.may_grant else 403,
        )

    def _client_error(self, reason: ClientRejection) -> TemplateResponse:
        # Without a verified redirect_uri there is nowhere safe to send the
        # error, so the user reads it here.
        logger.info("MCP OAuth client rejected: %s", reason)
        return TemplateResponse(
            self.request,
            TEMPLATE,
            {"client_error": _CLIENT_REJECTIONS[reason]},
            status=400,
        )


def _authorization_request(request: RootRequest) -> McpAuthorizationRequest:
    params = request.GET
    return {
        "client_id": params.get("client_id", ""),
        "redirect_uri": params.get("redirect_uri", ""),
        "response_type": params.get("response_type", ""),
        "code_challenge": params.get("code_challenge", ""),
        "code_challenge_method": params.get("code_challenge_method", ""),
        "state": params.get("state"),
        "scope": _scope_for_resource(request, params.get("resource", "")),
    }


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


def _redirect(
    request: RootRequest, *, redirect_uri: str, state: str | None, **params: str
) -> HttpResponse:
    query = params | {"iss": issuer(request)}
    if state is not None:
        query |= {"state": state}
    parts = urlsplit(redirect_uri)
    encoded = urlencode(query)
    return _ClientRedirect(
        urlunsplit(
            parts._replace(query=f"{parts.query}&{encoded}" if parts.query else encoded)
        )
    )


def _reject(
    request: RootRequest, rejection: McpAuthorizationRejectedError
) -> HttpResponse:
    return _redirect(
        request,
        redirect_uri=rejection.redirect_uri,
        state=rejection.state,
        error=rejection.error,
        error_description=rejection.description,
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
            grant = request.services.mcp_authorization.redeem(
                code=request.POST.get("code", ""),
                client_id=request.POST.get("client_id", ""),
                redirect_uri=request.POST.get("redirect_uri", ""),
                code_verifier=request.POST.get("code_verifier", ""),
            )
        except McpGrantRejectedError:
            logger.info(
                "MCP OAuth token refused: client=%s", request.POST.get("client_id", "")
            )
            return _token_error(
                "invalid_grant",
                "The authorization code is invalid or was issued for another request.",
            )
        logger.info("MCP OAuth token issued: user=%s", grant.user_id)
        response = JsonResponse(
            {
                "access_token": _mint(grant),
                "token_type": "Bearer",
                "expires_in": TOKEN_MAX_AGE_DAYS * 24 * 60 * 60,
            }
        )
        response["Cache-Control"] = "no-store"
        return response


def _mint(grant: McpGrant) -> str:
    match grant:
        case MaintainerGrant(user_id=user_id):
            return mint_token(user_id)
        case OrganizerGrant(user_id=user_id, sphere_id=sphere_id, event_id=event_id):
            return mint_organizer_token(
                user_id=user_id, sphere_id=sphere_id, event_id=event_id
            )


def _token_error(error: str, description: str) -> JsonResponse:
    response = JsonResponse(
        {"error": error, "error_description": description}, status=400
    )
    response["Cache-Control"] = "no-store"
    return response
