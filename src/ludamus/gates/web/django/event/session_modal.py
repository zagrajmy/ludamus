from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from django.http import Http404
from django.template.response import TemplateResponse
from django.views.generic.base import View

from ludamus.gates.web.django.chronology.event_presentation import present_session_modal
from ludamus.gates.web.django.event.enroll_presentation import build_enroll_footer
from ludamus.gates.web.django.helpers import read_public_event
from ludamus.gates.web.django.sphere.pages import EventsPageRequiredMixin
from ludamus.pacts import NotFoundError
from ludamus.pacts.ids import SessionId, UserId

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.gates.web.django.entities import RootRequest
    from ludamus.pacts import EventDTO


class SessionModalComponentView(EventsPageRequiredMixin, View):
    request: RootRequest

    def get(
        self, request: RootRequest, *, event_slug: str, session_id: int
    ) -> HttpResponse:
        event = read_public_event(self.request, event_slug)
        shadowbanned_ids, banned_by, event_banned = self._safety(event)
        dto = request.services.session_modal.read(
            event_id=event.pk,
            session_id=SessionId(session_id),
            viewer_user_ids=self._viewer_user_ids(),
            editor_user_id=self.request.context.current_user_id,
        )
        if dto is None:
            raise Http404
        access = request.services.enrollment.access(
            event=event, viewer_slug=request.context.current_user_slug
        )
        data = present_session_modal(
            dto,
            event_banned=event_banned,
            banned_presenter_ids=banned_by,
            shadowbanned_ids=shadowbanned_ids,
            access=access,
            guild=request.services.guilds.mark_for_session(
                sphere_id=request.context.current_sphere_id, session_pk=session_id
            ),
        )
        footer = build_enroll_footer(
            opens_at=access.opens_at,
            is_scheduled=not data.is_unscheduled,
            participants_limit=data.session.participants_limit,
            is_enrollment_available=data.is_enrollment_available,
            is_ended=data.is_ended,
            is_full=data.is_full,
            user_enrolled=data.user_enrolled,
            user_waiting=data.user_waiting,
        )
        return TemplateResponse(
            request,
            "chronology/parts/session-modal.html",
            {
                "data": data,
                "event": event,
                "event_banned": event_banned,
                # The plan the room is drawn on; a proposal has no room yet.
                "map_pk": (
                    None
                    if data.is_unscheduled
                    else request.services.event_maps.map_pk_for_space(
                        event_pk=event.pk, space_pk=data.loc["space_id"]
                    )
                ),
                # Drives both the tab bar and the roster panel it selects, so a
                # panel can never render without a tab owning it. An organizer
                # can drop a limit to 0 after people have signed up: those
                # participations still exist, and the people holding them have
                # to be able to see they are on the list.
                "show_roster": (
                    data.takes_enrollment or bool(data.session_participations)
                ),
                # Modal-only: the event page patches is_ended onto its cards
                # after construction, so this is wrong on a card.
                "enroll_actions": footer.actions,
                "enroll_opens_at": footer.opens_at,
            },
        )

    def _safety(self, event: EventDTO) -> tuple[frozenset[UserId], set[UserId], bool]:
        shadowbanned_ids: frozenset[UserId] = frozenset()
        banned_by: set[UserId] = set()
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

    def _viewer_user_ids(self) -> list[UserId]:
        if (slug := self.request.context.current_user_slug) is not None:
            user_id = self.request.context.current_user_id
            ids = [user_id] if user_id is not None else []
            ids.extend(
                companion.pk
                for companion in self.request.services.companions.list_companions(slug)
            )
            return ids
        return self._anonymous_viewer_user_ids()

    def _anonymous_viewer_user_ids(self) -> list[UserId]:
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
