"""Read models that compose a session with its seats, slot and people."""

from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel

from ludamus.pacts.enrollment import SessionParticipationStatus, SessionSeatsDTO
from ludamus.pacts.event import EventDTO, TimeSlotDTO
from ludamus.pacts.fields import SessionFieldValueDTO
from ludamus.pacts.ids import EventId
from ludamus.pacts.party import PartyDTO
from ludamus.pacts.sessions import SessionDTO
from ludamus.pacts.timetable import AgendaItemDTO
from ludamus.pacts.user import UserDTO
from ludamus.pacts.venues import LocationData, SpaceOptionDTO

if TYPE_CHECKING:
    from ludamus.pacts.ids import SessionId, UserId


class PlacementAvailabilityDTO(BaseModel):
    """Where a proposal can still go: the placements accepting will not refuse.

    ``taken_space_ids_by_slot`` maps a time slot to the spaces another session
    holds then. The rest is what neither choice can offer whatever the other
    holds: a space taken in every slot, a slot with every space taken.
    """

    taken_space_ids_by_slot: dict[int, list[int]]
    taken_space_ids: list[int]
    full_time_slot_ids: list[int]
    has_free_placement: bool


class ProposalAcceptContextDTO(BaseModel):
    session: SessionDTO
    event: EventDTO
    presenter: UserDTO | None
    space_options: list[SpaceOptionDTO]
    time_slots: list[TimeSlotDTO]
    preferred_time_slot_ids: list[int]
    field_values: list[SessionFieldValueDTO]
    can_accept: bool
    # False where the event lets a session be placed without a space.
    space_required: bool
    placements: PlacementAvailabilityDTO


class SessionSeatDTO(BaseModel):
    # One held seat, as every card-shaped read lists them: the party's
    # history, the detail modal and the event page's cards.
    user: UserDTO
    status: SessionParticipationStatus
    creation_time: datetime


class SessionCardStatsDTO(SessionSeatsDTO):
    waiting_count: int
    # The windows that can seat this session, by id — not whether enrollment
    # is available, which is a question about a viewer. Intersecting these
    # with the viewer's own open windows is the only way to that answer, so
    # every reader has to state whose windows it means.
    enrollment_window_ids: frozenset[int]


class PartySessionHistoryDTO(SessionCardStatsDTO):
    session: SessionDTO
    agenda_item: AgendaItemDTO
    presenter: UserDTO | None
    participations: list[SessionSeatDTO]
    location: LocationData
    viewer_enrolled: bool


class PartyEventHistoryDTO(BaseModel):
    event_pk: EventId
    event_name: str
    event_slug: str
    sessions: list[PartySessionHistoryDTO]


class PartyDetailDTO(BaseModel):
    party: PartyDTO
    history: list[PartyEventHistoryDTO]


class PartySessionHistoryRepositoryProtocol(Protocol):
    @staticmethod
    def list_for_party(
        *, party_pk: int, viewer_pk: int
    ) -> list[PartyEventHistoryDTO]: ...


class PartySessionHistoryServiceProtocol(Protocol):
    def read_detail(
        self, *, party_pk: int, viewer_pk: int
    ) -> PartyDetailDTO | None: ...


class SessionModalDTO(SessionCardStatsDTO):
    session: SessionDTO
    agenda_item: AgendaItemDTO
    presenter: UserDTO | None
    participations: list[SessionSeatDTO]
    location: LocationData
    field_values: list[SessionFieldValueDTO]
    viewer_enrolled: bool
    viewer_waiting: bool
    can_edit: bool
    is_ongoing: bool
    is_ended: bool


class SessionCardDTO(SessionCardStatsDTO):
    """One session as the event page's card, ledger row or room tile reads it."""

    session: SessionDTO
    # None while a proposal waits for a slot; every other field is filled
    # either way, so one card shape serves the schedule and the review queue.
    agenda_item: AgendaItemDTO | None
    presenter: UserDTO | None
    location: LocationData
    # Public fields only, in the organizer's field order.
    field_values: list[SessionFieldValueDTO]
    track_names: list[str]
    category_name: str
    # Empty when the reader asked for no roster: the card grid draws the first
    # seat holders, the compact ledger draws none and a big event has many.
    participations: list[SessionSeatDTO]
    # A proposal's acceptable slots, earliest first. A scheduled session states
    # its time through agenda_item and carries none.
    preferred_time_slots: list[TimeSlotDTO]


class SessionModalRepositoryProtocol(Protocol):
    @staticmethod
    def read_modal(
        *,
        event_id: EventId,
        session_id: SessionId,
        viewer_user_ids: list[UserId],
        editor_user_id: UserId | None,
    ) -> SessionModalDTO | None: ...


class SessionModalServiceProtocol(Protocol):
    def read(
        self,
        *,
        event_id: EventId,
        session_id: SessionId,
        viewer_user_ids: list[UserId],
        editor_user_id: UserId | None,
    ) -> SessionModalDTO | None: ...
