from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from django.http import Http404
from django.template.response import TemplateResponse
from django.views.generic.base import View

from ludamus.gates.web.django.access import has_panel_access
from ludamus.gates.web.django.chronology.event_presentation import present_session_modal
from ludamus.gates.web.django.event.enroll_presentation import build_enroll_actions
from ludamus.gates.web.django.helpers import is_event_published
from ludamus.pacts import NotFoundError

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.gates.web.django.entities import RootRequest
    from ludamus.pacts import EventDTO


class SessionModalComponentView(View):
    request: RootRequest

    def get(
        self, request: RootRequest, *, event_slug: str, session_id: int
    ) -> HttpResponse:
        event = self._get_event(event_slug)
        shadowbanned_ids, banned_by, event_banned = self._safety(event)
        dto = request.services.session_modal.read(
            event_id=event.pk,
            session_id=session_id,
            viewer_user_ids=self._viewer_user_ids(),
            editor_user_id=self.request.context.current_user_id,
        )
        if dto is None:
            raise Http404
        data = present_session_modal(
            dto,
            event_banned=event_banned,
            banned_presenter_ids=banned_by,
            shadowbanned_ids=shadowbanned_ids,
            guild=request.services.guilds.mark_for_session(
                sphere_id=request.context.current_sphere_id, session_pk=session_id
            ),
        )
        return TemplateResponse(
            request,
            "chronology/parts/session-modal.html",
            {
                "data": data,
                "event": event,
                "event_banned": event_banned,
                # Modal-only: the event page patches is_ended onto its cards
                # after construction, so this is wrong on a card.
                "enroll_actions": build_enroll_actions(
                    is_enrollment_available=data.is_enrollment_available,
                    is_ended=data.is_ended,
                    is_full=data.is_full,
                    user_enrolled=data.user_enrolled,
                    user_waiting=data.user_waiting,
                ),
            },
        )

    def _get_event(self, event_slug: str) -> EventDTO:
        try:
            event = self.request.services.events.read_by_slug(
                self.request.context.current_sphere_id, event_slug
            )
        except NotFoundError as exc:
            raise Http404 from exc
        if not is_event_published(event) and not has_panel_access(self.request):
            raise Http404
        return event

    def _safety(self, event: EventDTO) -> tuple[frozenset[int], set[int], bool]:
        shadowbanned_ids: frozenset[int] = frozenset()
        banned_by: set[int] = set()
        event_banned = False
        if (current_user_id := self.request.context.current_user_id) is not None:
            banned_by = self.request.services.shadowban.banning_owner_ids(
                current_user_id
            )
            shadowbanned_ids = frozenset(
                self.request.services.shadowban.banned_user_ids(current_user_id)
            )
            event_banned = self.request.services.event_bans.is_banned(
                event_id=event.pk, user_id=current_user_id
            )
        return shadowbanned_ids, banned_by, event_banned

    def _viewer_user_ids(self) -> list[int]:
        if (slug := self.request.context.current_user_slug) is not None:
            user_id = self.request.context.current_user_id
            ids = [user_id] if user_id is not None else []
            ids.extend(
                companion.pk
                for companion in self.request.services.companions.list_companions(slug)
            )
            return ids
        return self._anonymous_viewer_user_ids()

    def _anonymous_viewer_user_ids(self) -> list[int]:
        session = self.request.session
        if not session.get("anonymous_enrollment_active"):
            return []
        code = session.get("anonymous_user_code")
        if code is None or (
            session.get("anonymous_site_id") != self.request.context.current_site_id
        ):
            return []
        with contextlib.suppress(NotFoundError):
            user = self.request.services.anonymous_enrollment.get_user_by_code(
                code=code
            )
            return [user.pk]
        return []
