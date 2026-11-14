"""The sphere's chats its organizers moderate without being in them."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from django.http import Http404
from django.template.response import TemplateResponse
from django.views.generic.base import View

from ludamus.gates.web.django.access import panel_access
from ludamus.gates.web.django.sphere.access import SphereAccessMixin
from ludamus.gates.web.django.sphere.panel_context import sphere_sidebar_context
from ludamus.pacts.sphere import Capability

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.gates.web.django.panel import PanelRequest

logger = logging.getLogger(__name__)


class ChatModerationPageView(SphereAccessMixin, View):
    request: PanelRequest

    def get(
        self, _request: PanelRequest, kind: str | None = None, pk: int | None = None
    ) -> HttpResponse:
        if not panel_access(self.request).allows(Capability.CHAT_MODERATE):
            raise Http404
        user_id = self.request.context.current_user_id
        rooms = self.request.services.parley.moderated_rooms(
            user_id=user_id,
            sphere_id=self.request.context.current_sphere_id,
            now=datetime.now(tz=UTC),
        )
        room = None
        if kind is not None:
            room = next(
                (each for each in rooms if each.kind == kind and each.pk == pk), None
            )
            if room is None:
                raise Http404
            logger.info(
                "chat moderation room opened: user=%s room=%s", user_id, room.id
            )
        return TemplateResponse(
            self.request,
            "sphere/panel/chats.html",
            {
                **sphere_sidebar_context(self.request, active_nav="chats"),
                "rooms": rooms,
                "room": room,
            },
        )
