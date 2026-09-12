from datetime import datetime
from enum import StrEnum
from typing import Protocol, TypedDict

from pydantic import BaseModel, ConfigDict

from ludamus.pacts.guild import GuildMarkDTO
from ludamus.pacts.legacy import (
    EventDTO,
    EventListItemDTO,
    EventRepositoryProtocol,
    PanelStatsDTO,
    TimeSlotDTO,
)


class EventCreateData(TypedDict):
    name: str
    slug: str
    description: str
    start_time: datetime
    end_time: datetime
    publication_time: datetime | None
    auto_confirm_sessions: bool


class EventSlugConflictError(Exception):
    pass


class EventDatesInvalidError(Exception):
    pass


class EventPublicationInvalidError(Exception):
    pass


class EventsRepositoryProtocol(EventRepositoryProtocol, Protocol):
    @staticmethod
    def create(sphere_id: int, data: EventCreateData) -> EventDTO: ...
    @staticmethod
    def read_in_sphere(pk: int, sphere_id: int) -> EventDTO: ...
    @staticmethod
    def slug_exists(sphere_id: int, slug: str) -> bool: ...


class EventsServiceProtocol(Protocol):
    def list_for_sphere(
        self, sphere_id: int, *, include_unpublished: bool
    ) -> list[EventListItemDTO]: ...
    def read_by_slug(self, sphere_id: int, slug: str) -> EventDTO: ...
    def require_in_sphere(self, *, sphere_id: int, event_id: int) -> EventDTO: ...
    def create(self, *, sphere_id: int, data: EventCreateData) -> EventDTO: ...


class FacilitatorListItemDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    accreditation_type: str
    deleted_at: datetime | None = None
    display_name: str
    # Attached by the panel view, not the ORM. Null means no guild.
    guild: GuildMarkDTO | None = None
    organizer_id: int | None = None
    # Annotated by `list_by_event`; null when nobody took the facilitator on.
    organizer_name: str | None = None
    pk: int
    session_count: int
    slug: str
    user_id: int | None


class TimeSlotValidationError(StrEnum):
    START_NOT_BEFORE_END = "start_not_before_end"
    OUTSIDE_EVENT_DATES = "outside_event_dates"
    OVERLAPS_EXISTING_SLOT = "overlaps_existing_slot"


class TimeSlotRejectedError(Exception):
    def __init__(self, errors: list[TimeSlotValidationError]) -> None:
        super().__init__(", ".join(error.value for error in errors))
        self.errors = errors


class EventPanelContextDTO(BaseModel):
    events: list[EventDTO]
    current_event: EventDTO
    is_proposal_active: bool
    stats: PanelStatsDTO


class EventPanelServiceProtocol(Protocol):
    def load_context(self, sphere_id: int, slug: str) -> EventPanelContextDTO: ...


class ConfirmationOrganizerRowDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    organizer_id: int | None
    organizer_name: str
    facilitator_count: int
    scheduled_count: int
    confirmed_count: int
    progress_pct: int


class ConfirmationTrackRowDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    track_pk: int
    track_name: str
    manager_names: list[str]
    facilitator_count: int
    scheduled_count: int
    confirmed_count: int
    progress_pct: int


class ConfirmationDashboardDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    organizers: list[ConfirmationOrganizerRowDTO]
    tracks: list[ConfirmationTrackRowDTO]
    scheduled_count: int
    confirmed_count: int
    progress_pct: int
    claimed_facilitator_count: int
    unclaimed_facilitator_count: int
    # Scheduled sessions nobody facilitates: they cannot show up in a
    # facilitator-keyed list, so the dashboard counts them out loud.
    without_facilitator_count: int


class ConfirmationSessionDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_pk: int
    title: str
    category_name: str
    room_name: str
    start_time: datetime | None
    end_time: datetime | None
    # Only a scheduled item can be confirmed, so only a scheduled item carries
    # an agenda item pk — the template hangs the checkbox off it.
    agenda_item_pk: int | None
    is_confirmed: bool
    co_facilitator_names: list[str]
    other_track_names: list[str]


class ConfirmationStatusGroupDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str
    sessions: list[ConfirmationSessionDTO]


class ConfirmationEmailGroupDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    contact_email: str
    status_groups: list[ConfirmationStatusGroupDTO]
    confirmable_count: int


class ConfirmationFacilitatorDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    display_name: str
    organizer_name: str
    organizer_id: int | None
    pk: int
    slug: str
    email_groups: list[ConfirmationEmailGroupDTO]
    scheduled_count: int
    confirmed_count: int
    # Decided but not placed, and still awaiting a decision: counted, never
    # listed — there is nothing to tick on either.
    unplaced_count: int
    pending_count: int
    is_fully_confirmed: bool


class ConfirmationTrackViewDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    facilitators: list[ConfirmationFacilitatorDTO]
    facilitator_count: int
    unclaimed_facilitator_count: int
    # Counted over this track only, while a facilitator's own counter spans the
    # whole event.
    scheduled_count: int
    confirmed_count: int
    progress_pct: int
    # Placed in this track but facilitated by nobody, so absent from every card
    # above — and from the counts. Reported so the two numbers reconcile.
    without_facilitator_count: int


class EventConfirmationsServiceProtocol(Protocol):
    def dashboard(self, event_pk: int) -> ConfirmationDashboardDTO: ...
    def track_view(
        self, *, event_pk: int, track_pk: int
    ) -> ConfirmationTrackViewDTO: ...
    def facilitator_card(
        self, *, event_pk: int, track_pk: int, facilitator_pk: int
    ) -> ConfirmationFacilitatorDTO: ...
    def set_confirmed(
        self,
        *,
        event_pk: int,
        facilitator_pk: int,
        confirmed: bool,
        contact_email: str | None = None,
        agenda_item_pk: int | None = None,
    ) -> None: ...


class PanelTimeSlotsServiceProtocol(Protocol):
    def list_for_event(self, event_id: int) -> list[TimeSlotDTO]: ...
    def undeletable_pks(self, event_id: int) -> frozenset[int]: ...
    def read(self, *, event_id: int, pk: int) -> TimeSlotDTO: ...
    def create(
        self, *, event: EventDTO, start_time: datetime, end_time: datetime
    ) -> TimeSlotDTO: ...
    def update(
        self, *, event: EventDTO, pk: int, start_time: datetime, end_time: datetime
    ) -> None: ...
    def delete(self, *, event_id: int, pk: int) -> bool: ...


class LandingStatsDTO(BaseModel):
    events: int
    sessions: int


class LandingStatsRepositoryProtocol(Protocol):
    @staticmethod
    def count_landing_stats() -> LandingStatsDTO: ...


class LandingServiceProtocol(Protocol):
    def stats(self) -> LandingStatsDTO: ...
