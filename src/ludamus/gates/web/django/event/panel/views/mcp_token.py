from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.generic.base import View

from ludamus.gates.web.django.event.panel.views.base import (
    EventContextMixin,
    EventPanelAccessMixin,
    EventPanelRequest,
)
from ludamus.gates.web.django.mcp.tokens import TOKEN_MAX_AGE_DAYS, mint_organizer_token
from ludamus.gates.web.django.panel import settings_tab_urls

if TYPE_CHECKING:
    from django.http import HttpResponse

TEMPLATE = "panel/mcp-token.html"


class EventMcpTokenPageView(EventPanelAccessMixin, EventContextMixin, View):
    request: EventPanelRequest

    def get(self, _request: EventPanelRequest, slug: str) -> HttpResponse:
        return self._render(slug=slug, token=None)

    def post(self, _request: EventPanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.require_event_context(slug)
        token = mint_organizer_token(
            user_id=self.request.context.current_user_id,
            sphere_id=self.request.context.current_sphere_id,
            event_id=current_event.pk,
        )
        return self._render(slug=slug, token=token, context=context)

    def _render(
        self, *, slug: str, token: str | None, context: dict[str, Any] | None = None
    ) -> HttpResponse:
        if context is None:
            context, _current_event = self.require_event_context(slug)
        context.update(
            active_nav="settings",
            active_tab="mcp",
            tab_urls=settings_tab_urls(slug),
            token=token,
            endpoint_url=self.request.build_absolute_uri(
                reverse("mcp:organizer-endpoint")
            ),
            token_max_age_days=TOKEN_MAX_AGE_DAYS,
        )
        return TemplateResponse(self.request, TEMPLATE, context)
