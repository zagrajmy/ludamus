"""HTTP gate for the maintainer MCP server.

`/mcp/` is a stateless MCP Streamable HTTP endpoint. Access is maintainer-only:
a signed Bearer token minted at `/mcp/token/` by a logged-in superuser. The
token embeds the user id; every request re-checks that the user is still an
active superuser, so revoking access is flipping the flag in Django admin.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core import signing
from django.http import Http404, HttpResponse, JsonResponse
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from ludamus.gates.mcp.protocol import PARSE_ERROR, error_response, handle_message
from ludamus.gates.mcp.tools import build_registry

if TYPE_CHECKING:
    from ludamus.gates.web.django.entities import AuthenticatedRootRequest, RootRequest

SIGNING_SALT = "ludamus.mcp"
TOKEN_MAX_AGE_DAYS = 30

_REGISTRY = build_registry()


def mint_token(user_id: int) -> str:
    return signing.dumps({"user_id": user_id}, salt=SIGNING_SALT)


def _authenticated_superuser_id(request: RootRequest) -> int | None:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    try:
        payload = signing.loads(
            header.removeprefix("Bearer "),
            salt=SIGNING_SALT,
            max_age=TOKEN_MAX_AGE_DAYS * 24 * 60 * 60,
        )
    except signing.BadSignature:
        return None
    user_id = payload.get("user_id") if isinstance(payload, dict) else None
    if not isinstance(user_id, int):
        return None
    user_model = get_user_model()
    is_superuser = user_model.objects.filter(
        pk=user_id, is_active=True, is_superuser=True
    ).exists()
    return user_id if is_superuser else None


@method_decorator(csrf_exempt, name="dispatch")
class McpEndpointView(View):
    """Bearer-token JSON-RPC endpoint; CSRF does not apply (no cookie auth)."""

    request: RootRequest

    @staticmethod
    def post(request: RootRequest) -> HttpResponse:
        if (actor_id := _authenticated_superuser_id(request)) is None:
            response = JsonResponse(
                {"error": "A valid maintainer Bearer token is required."}, status=401
            )
            response["WWW-Authenticate"] = "Bearer"
            return response

        try:
            message = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse(
                error_response(
                    message_id=None, code=PARSE_ERROR, message="Parse error"
                ),
                status=400,
            )
        if not isinstance(message, dict):
            return JsonResponse(
                error_response(
                    message_id=None,
                    code=PARSE_ERROR,
                    message="Expected a JSON-RPC object",
                ),
                status=400,
            )

        result = handle_message(
            registry=_REGISTRY,
            services=request.services,
            actor_id=actor_id,
            message=message,
        )
        if result is None:
            return HttpResponse(status=202)
        return JsonResponse(result)


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
