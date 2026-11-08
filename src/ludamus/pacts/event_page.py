"""Contracts for the public event page: its schedule and what a viewer holds."""

from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel

from ludamus.pacts.enrollment import SessionParticipationStatus

if TYPE_CHECKING:
    from collections.abc import Collection

    from ludamus.pacts.chronology import SessionCardDTO
    from ludamus.pacts.fields import OrganizerFieldDTO
    from ludamus.pacts.ids import EventId, SessionId, UserId


class SeatStatusDTO(BaseModel):
    session_id: int
    status: SessionParticipationStatus


class ViewerSeatsDTO(BaseModel):
    """What the viewer (and the people they act for) hold in one session."""

    enrolled: bool = False
    waiting: bool = False


class EnrollmentNoticesDTO(BaseModel):
    # The open windows' banners, in window order.
    banners: list[str]
    # An open window seats only sessions starting before it ends, so a
    # session already under way reads as in progress rather than open.
    limits_to_end_time: bool


class EventScheduleRepositoryProtocol(Protocol):
    @staticmethod
    def scheduled_cards(
        *, event_id: EventId, roster_up_to: int
    ) -> list[SessionCardDTO]: ...
    @staticmethod
    def review_queue(event_id: EventId) -> list[SessionCardDTO]: ...
    @staticmethod
    def own_proposals(
        *, event_id: EventId, presenter_id: UserId
    ) -> list[SessionCardDTO]: ...
    @staticmethod
    def seat_statuses(
        *, session_ids: Collection[int], user_ids: Collection[int]
    ) -> list[SeatStatusDTO]: ...


class EventScheduleServiceProtocol(Protocol):
    def scheduled_cards(
        self, *, event_id: EventId, roster_up_to: int
    ) -> list[SessionCardDTO]: ...
    def review_queue(self, event_id: EventId) -> list[SessionCardDTO]: ...
    def own_proposals(
        self, *, event_id: EventId, presenter_id: UserId
    ) -> list[SessionCardDTO]: ...
    def viewer_seats(
        self, *, session_ids: Collection[int], user_ids: Collection[int]
    ) -> dict[SessionId, ViewerSeatsDTO]: ...
    def enrollment_notices(self, event_id: EventId) -> EnrollmentNoticesDTO: ...
    def public_select_fields(self, event_id: EventId) -> list[OrganizerFieldDTO]: ...
