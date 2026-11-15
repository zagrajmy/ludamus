"""The sphere's chats its organizers moderate without being in them."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from django.http import Http404
from django.template.response import TemplateResponse
from django.views.generic.base import View

from ludamus.gates.web.django.panel import refuse_panel_access
from ludamus.gates.web.django.sphere.access import SphereAccessMixin
from ludamus.gates.web.django.sphere.panel_context import sphere_sidebar_context
from ludamus.pacts.errors import NotFoundError

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.gates.web.django.panel import PanelRequest

logger = logging.getLogger(__name__)


class ChatModerationPageView(SphereAccessMixin, View):
    request: PanelRequest

    def get(
        self, _request: PanelRequest, kind: str | None = None, pk: int | None = None
    ) -> HttpResponse:
        parley = self.request.services.parley
        user_id = self.request.context.current_user_id
        sphere_id = self.request.context.current_sphere_id
        if not parley.moderates(user_id=user_id, sphere_id=sphere_id):
            return refuse_panel_access(
                request=self.request,
                reads_panel=True,
                message=str(self.no_permission_message),
            )
        try:
            page = parley.moderation_page(
                user_id=user_id,
                sphere_id=sphere_id,
                room=None if kind is None or pk is None else (kind, pk),
                now=datetime.now(tz=UTC),
            )
        except NotFoundError as error:
            raise Http404 from error
        if page.room is not None:
            logger.info(
                "chat moderation room opened: user=%s room=%s", user_id, page.room.id
            )
        return TemplateResponse(
            self.request,
            "sphere/panel/chats.html",
            {**sphere_sidebar_context(self.request, active_nav="chats"), "page": page},
        )
