"""The sphere's chats its organizers moderate without being in them."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from django.http import Http404
from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.generic.base import View

from ludamus.gates.web.django.parley.configuration import chat_configured
from ludamus.gates.web.django.sphere.access import SphereAccessMixin
from ludamus.gates.web.django.sphere.panel_context import sphere_sidebar_context
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.parley import ParleyOpenedRoomDTO, ParleyRoomKind, ParleyRoomRef

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


def _public_url(opened: ParleyOpenedRoomDTO) -> str:
    event_url = reverse("web:chronology:event", kwargs={"slug": opened.event_slug})
    if opened.room.kind == ParleyRoomKind.EVENT:
        return event_url
    return f"{event_url}?session={opened.room.pk}"


class ChatModerationPageView(SphereAccessMixin, View):
    request: PanelRequest

    def get(
        self, _request: PanelRequest, *, kind: str | None = None, pk: int | None = None
    ) -> HttpResponse:
        if not chat_configured():
            raise Http404
        user_id = self.request.context.current_user_id
        try:
            page = self.request.services.parley.moderation_page(
                user_id=user_id,
                sphere_id=self.request.context.current_sphere_id,
                room=_room(kind, pk),
                now=datetime.now(tz=UTC),
            )
        except NotFoundError as error:
            raise Http404 from error
        opened_room_id = None if page.opened is None else page.opened.room.id
        if opened_room_id is not None:
            logger.info(
                "chat moderation room opened: user=%s room=%s", user_id, opened_room_id
            )
        return TemplateResponse(
            self.request,
            "sphere/panel/chats.html",
            {
                **sphere_sidebar_context(self.request, active_nav="chats"),
                "page": page,
                "opened_room_id": opened_room_id,
                "opened_url": None if page.opened is None else _public_url(page.opened),
            },
        )
