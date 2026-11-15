"""The sphere's chats its organizers moderate without being in them."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from django.http import Http404
from django.template.response import TemplateResponse
from django.views.generic.base import View

from ludamus.gates.web.django.context_processors import parley_open
from ludamus.gates.web.django.sphere.access import SphereAccessMixin
from ludamus.gates.web.django.sphere.panel_context import sphere_sidebar_context
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.parley import ParleyRoomKind, ParleyRoomRef

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.gates.web.django.panel import PanelRequest

logger = logging.getLogger(__name__)


def _room(kind: str | None, pk: int | None) -> ParleyRoomRef | None:
    if kind is None or pk is None:
        return None
    try:
        return ParleyRoomRef(kind=ParleyRoomKind(kind), pk=pk)
    except ValueError as error:
        raise Http404 from error


class ChatModerationPageView(SphereAccessMixin, View):
    request: PanelRequest

    def get(
        self, _request: PanelRequest, kind: str | None = None, pk: int | None = None
    ) -> HttpResponse:
        user_id = self.request.context.current_user_id
        if not parley_open(user_id=user_id, services=self.request.services):
            raise Http404
        try:
            page = self.request.services.parley.moderation_page(
                user_id=user_id,
                sphere_id=self.request.context.current_sphere_id,
                room=_room(kind, pk),
                now=datetime.now(tz=UTC),
            )
        except NotFoundError as error:
            raise Http404 from error
        if page.opened is not None:
            logger.info(
                "chat moderation room opened: user=%s room=%s",
                user_id,
                page.opened.room.id,
            )
        return TemplateResponse(
            self.request,
            "sphere/panel/chats.html",
            {**sphere_sidebar_context(self.request, active_nav="chats"), "page": page},
        )
