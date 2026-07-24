"""HTTP gates for the MCP endpoints.

`/mcp/` (maintainer) and `/mcp/organizer/` are stateless MCP Streamable HTTP
endpoints. Token minting and verification live in `tokens.py`; each endpoint
loads only its tier's tool registry.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponse, JsonResponse
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from ludamus.gates.mcp.protocol import PARSE_ERROR, error_response, handle_message
from ludamus.gates.mcp.tools import build_registry
from ludamus.gates.web.django.mcp.tokens import (
    TOKEN_MAX_AGE_DAYS,
    authenticate_maintainer,
    authenticate_organizer,
    mint_token,
)
from ludamus.pacts.mcp import ToolScope

if TYPE_CHECKING:
    from ludamus.gates.mcp.registry import ToolRegistry
    from ludamus.gates.web.django.entities import AuthenticatedRootRequest, RootRequest
    from ludamus.pacts.mcp import ActorContext

_MAINTAINER_REGISTRY = build_registry(ToolScope.MAINTAINER)
_ORGANIZER_REGISTRY = build_registry(ToolScope.ORGANIZER)


def _unauthorized(missing: str) -> JsonResponse:
    response = JsonResponse(
        {"error": f"A valid {missing} Bearer token is required."}, status=401
    )
    response["WWW-Authenticate"] = "Bearer"
    return response


def _dispatch(
    *, request: RootRequest, registry: ToolRegistry, actor: ActorContext
) -> HttpResponse:
    try:
        message = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse(
            error_response(message_id=None, code=PARSE_ERROR, message="Parse error"),
            status=400,
        )
    if not isinstance(message, dict):
        return JsonResponse(
            error_response(
                message_id=None, code=PARSE_ERROR, message="Expected a JSON-RPC object"
            ),
            status=400,
        )

    result = handle_message(
        registry=registry, services=request.services, actor=actor, message=message
    )
    if result is None:
        return HttpResponse(status=202)
    return JsonResponse(result)


@method_decorator(csrf_exempt, name="dispatch")
class McpEndpointView(View):
    """Bearer-token JSON-RPC endpoint; CSRF does not apply (no cookie auth)."""

    request: RootRequest

    @staticmethod
    def post(request: RootRequest) -> HttpResponse:
        if (actor := authenticate_maintainer(request)) is None:
            return _unauthorized("maintainer")
        return _dispatch(request=request, registry=_MAINTAINER_REGISTRY, actor=actor)


@method_decorator(csrf_exempt, name="dispatch")
class McpOrganizerEndpointView(View):
    """Sphere-scoped organizer endpoint; tools read the sphere from the token."""

    request: RootRequest

    @staticmethod
    def post(request: RootRequest) -> HttpResponse:
        if (actor := authenticate_organizer(request)) is None:
            return _unauthorized("organizer")
        return _dispatch(request=request, registry=_ORGANIZER_REGISTRY, actor=actor)


class McpTokenPageView(LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    def get(self, request: AuthenticatedRootRequest) -> TemplateResponse:
        _require_superuser(request)
        return TemplateResponse(request, "mcp/token.html", self._context(request))

    def post(self, request: AuthenticatedRootRequest) -> TemplateResponse:
        user_pk = _require_superuser(request)
        context = self._context(request) | {"token": mint_token(user_pk)}
        return TemplateResponse(request, "mcp/token.html", context)

    @staticmethod
    def _context(request: AuthenticatedRootRequest) -> dict[str, object]:
        return {
            "token": None,
            "endpoint_url": request.build_absolute_uri(reverse("mcp:endpoint")),
            "token_max_age_days": TOKEN_MAX_AGE_DAYS,
        }


def _require_superuser(request: AuthenticatedRootRequest) -> int:
    user_pk = request.user.pk
    if user_pk is None or not request.user.is_superuser:
        raise Http404
    return user_pk
