"""Sphere-panel page minting organizer MCP tokens."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.generic.base import View

from ludamus.gates.web.django.mcp.tokens import TOKEN_MAX_AGE_DAYS, mint_organizer_token
from ludamus.gates.web.django.multiverse.access import (
    MultiverseRequest,
    SphereAccessMixin,
)
from ludamus.gates.web.django.multiverse.panel.views.base import sphere_panel_context

if TYPE_CHECKING:
    from django.http import HttpResponse

TEMPLATE = "multiverse/panel/mcp-token.html"


class OrganizerMcpTokenPageView(SphereAccessMixin, View):
    request: MultiverseRequest

    def get(self, _request: MultiverseRequest) -> HttpResponse:
        return TemplateResponse(self.request, TEMPLATE, self._context(token=None))

    def post(self, _request: MultiverseRequest) -> HttpResponse:
        token = mint_organizer_token(
            user_id=self.request.context.current_user_id,
            sphere_id=self.request.context.current_sphere_id,
        )
        return TemplateResponse(self.request, TEMPLATE, self._context(token=token))

    def _context(self, *, token: str | None) -> dict[str, Any]:
        return sphere_panel_context(self.request, active_tab="mcp") | {
            "token": token,
            "endpoint_url": self.request.build_absolute_uri(
                reverse("mcp:organizer-endpoint")
            ),
            "token_max_age_days": TOKEN_MAX_AGE_DAYS,
        }
