"""The public event page's reads: its schedule, proposals and a viewer's seats."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ludamus.pacts.enrollment import SessionParticipationStatus, open_windows
from ludamus.pacts.event_page import (
    EnrollmentNoticesDTO,
    EventScheduleServiceProtocol,
    ViewerSeatsDTO,
)
from ludamus.pacts.ids import SessionId

if TYPE_CHECKING:
    from collections.abc import Collection

    from ludamus.pacts.enrollment import EnrollmentWindowRepositoryProtocol
    from ludamus.pacts.event_page import EventScheduleRepositoryProtocol
    from ludamus.pacts.fields import OrganizerFieldDTO, SessionFieldRepositoryProtocol
    from ludamus.pacts.ids import EventId, UserId
    from ludamus.pacts.session_cards import SessionCardDTO


class EventScheduleService(EventScheduleServiceProtocol):
    def __init__(
        self,
        *,
        schedule: EventScheduleRepositoryProtocol,
        windows: EnrollmentWindowRepositoryProtocol,
        session_fields: SessionFieldRepositoryProtocol,
    ) -> None:
        self._schedule = schedule
        self._windows = windows
        self._session_fields = session_fields

    def scheduled_cards(
        self, *, event_id: EventId, roster_up_to: int
    ) -> list[SessionCardDTO]:
        return self._schedule.scheduled_cards(
            event_id=event_id, roster_up_to=roster_up_to
        )

    def review_queue(self, event_id: EventId) -> list[SessionCardDTO]:
        return self._schedule.review_queue(event_id)

    def own_proposals(
        self, *, event_id: EventId, presenter_id: UserId
    ) -> list[SessionCardDTO]:
        return self._schedule.own_proposals(
            event_id=event_id, presenter_id=presenter_id
        )

    def viewer_seats(
        self, *, session_ids: Collection[int], user_ids: Collection[int]
    ) -> dict[SessionId, ViewerSeatsDTO]:
        # A seat held by any of these people marks the session: a viewer's
        # card shows what they and the companions they act for hold.
        seats: dict[SessionId, ViewerSeatsDTO] = {}
        for seat in self._schedule.seat_statuses(
            session_ids=session_ids, user_ids=user_ids
        ):
            held = seats.setdefault(SessionId(seat.session_id), ViewerSeatsDTO())
            held.enrolled |= seat.status == SessionParticipationStatus.CONFIRMED
            held.waiting |= seat.status == SessionParticipationStatus.WAITING
        return seats

    def enrollment_notices(self, event_id: EventId) -> EnrollmentNoticesDTO:
        opened = open_windows(
            self._windows.list_for_event(event_id), now=datetime.now(tz=UTC)
        )
        return EnrollmentNoticesDTO(
            banners=[window.banner_text for window in opened if window.banner_text],
            limits_to_end_time=any(window.limit_to_end_time for window in opened),
        )

    def public_select_fields(self, event_id: EventId) -> list[OrganizerFieldDTO]:
        # The filter panel offers only what a participant may see, and only
        # fields with options to narrow by.
        return [
            field
            for field in self._session_fields.list_by_event(event_id)
            if field.field_type == "select" and field.is_public
        ]
