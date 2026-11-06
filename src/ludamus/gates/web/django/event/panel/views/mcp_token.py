from __future__ import annotations

from typing import TYPE_CHECKING

from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.generic.base import View

from ludamus.gates.web.django.event.panel.views.base import (
    EventPanelMixin,
    PanelContext,
)
from ludamus.gates.web.django.mcp.tokens import TOKEN_MAX_AGE_DAYS, mint_organizer_token
from ludamus.gates.web.django.panel import PanelRequest, settings_tab_urls

if TYPE_CHECKING:
    from django.http import HttpResponse

TEMPLATE = "panel/mcp-token.html"


@method_decorator(never_cache, name="dispatch")
class EventMcpTokenPageView(EventPanelMixin, View):
    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context = self.panel_context()
        return self._render(slug=slug, token=None, context=context)

    def post(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context = self.panel_context()
        token = mint_organizer_token(
            user_id=self.request.context.current_user_id,
            sphere_id=self.request.context.current_sphere_id,
            event_id=self.current_event.pk,
        )
        return self._render(slug=slug, token=token, context=context)

    def _render(
        self, *, slug: str, token: str | None, context: PanelContext
    ) -> HttpResponse:
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
