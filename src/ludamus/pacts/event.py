from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, TypedDict

from pydantic import BaseModel, ConfigDict

from ludamus.pacts.guild import GuildMarkDTO
from ludamus.pacts.ids import EventId, SphereId
from ludamus.pacts.sessions import SessionStatus

if TYPE_CHECKING:
    from ludamus.pacts.images import UploadedFileProtocol


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


class TimeSlotDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    end_time: datetime
    pk: int
    start_time: datetime


class EventVisibility(StrEnum):
    # PUBLIC follows publication_time: hidden before it, listed after it.
    # UNLISTED opens to anyone with the link whatever the publication time,
    # and is never listed or announced.
    PUBLIC = "public"
    UNLISTED = "unlisted"


class EventDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    address: str = ""
    allow_facilitator_session_edit: bool | None = None
    auto_confirm_sessions: bool = False
    description: str
    end_time: datetime
    name: str
    pk: EventId
    proposal_end_time: datetime | None
    proposal_start_time: datetime | None
    publication_time: datetime | None
    slug: str
    sphere_id: SphereId
    start_time: datetime
    use_session_cover_placeholders: bool = False
    use_participants_label: bool = False
    parley_enabled: bool = True
    visibility: EventVisibility = EventVisibility.PUBLIC
    cover_image_url: str = ""
    cover_image_original_name: str = ""
    logo_url: str = ""
    logo_original_name: str = ""

    @property
    def address_inline(self) -> str:
        """The address as one comma-joined line, for map and calendar links."""
        return ", ".join(
            line.strip() for line in self.address.splitlines() if line.strip()
        )

    @property
    def is_live(self) -> bool:
        return self.start_time < datetime.now(tz=UTC) < self.end_time

    @property
    def is_ended(self) -> bool:
        return self.end_time < datetime.now(tz=UTC)

    @property
    def is_published(self) -> bool:
        return (
            self.publication_time is not None
            and self.publication_time <= datetime.now(tz=UTC)
        )

    @property
    def is_open(self) -> bool:
        """Whether anyone with the link may open the event's pages."""
        return self.is_published or self.visibility is EventVisibility.UNLISTED

    @property
    def is_proposal_window_open(self) -> bool:
        """Whether the call for proposals' own dates have come, open or not."""
        current_time = datetime.now(tz=UTC)
        return bool(
            self.proposal_start_time is not None
            and self.proposal_end_time is not None
            and self.proposal_start_time <= current_time <= self.proposal_end_time
        )

    # Proposals only open on an event with a public page — without one there
    # is nowhere to send a facilitator.
    @property
    def is_proposal_active(self) -> bool:
        return self.is_open and self.is_proposal_window_open


class EventListItemDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    cover_image_url: str = ""
    description: str
    end_time: datetime
    is_ended: bool
    is_live: bool
    is_proposal_active: bool
    is_published: bool
    name: str
    session_count: int
    slug: str
    start_time: datetime
    visibility: EventVisibility = EventVisibility.PUBLIC


class EventProposalSettingsDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    allow_anonymous_proposals: bool
    description: str
    pk: int


class EventUpdateData(TypedDict, total=False):
    """Write shape for updating event fields."""

    name: str
    slug: str
    description: str
    address: str
    logo: UploadedFileProtocol | str
    cover_image: UploadedFileProtocol | str
    start_time: datetime
    end_time: datetime
    publication_time: datetime | None
    visibility: EventVisibility
    proposal_start_time: datetime | None
    proposal_end_time: datetime | None
    allow_facilitator_session_edit: bool | None
    auto_confirm_sessions: bool
    use_session_cover_placeholders: bool
    use_participants_label: bool
    parley_enabled: bool


class EventStatsData(BaseModel):
    """Raw statistics data from the repository."""

    model_config = ConfigDict(from_attributes=True)

    pending_proposals: int
    scheduled_sessions: int
    total_proposals: int
    hosts_count: int
    rooms_count: int


class PanelStatsDTO(EventStatsData):
    """Statistics for the backoffice panel dashboard."""

    total_sessions: int


class EventRepositoryProtocol(Protocol):
    @staticmethod
    def list_by_sphere(sphere_id: int) -> list[EventDTO]: ...
    @staticmethod
    def list_for_events_page(
        sphere_id: int, *, include_hidden: bool
    ) -> list[EventListItemDTO]: ...
    @staticmethod
    def read(pk: int) -> EventDTO: ...
    @staticmethod
    def read_by_slug(slug: str, sphere_id: int) -> EventDTO: ...
    @staticmethod
    def get_stats_data(event_id: int) -> EventStatsData: ...
    @staticmethod
    def update(event_id: int, data: EventUpdateData) -> None: ...
    @staticmethod
    def lock(event_id: int) -> None: ...


class TimeSlotRepositoryProtocol(Protocol):
    @staticmethod
    def create(
        event_id: int, start_time: datetime, end_time: datetime
    ) -> TimeSlotDTO: ...
    @staticmethod
    def get_or_create(
        event_id: int, start_time: datetime, end_time: datetime
    ) -> int: ...
    @staticmethod
    def delete(pk: int) -> None: ...
    @staticmethod
    def has_proposals(pk: int) -> bool: ...
    @staticmethod
    def pks_with_proposals(event_id: int) -> frozenset[int]: ...
    @staticmethod
    def list_by_event(event_id: int) -> list[TimeSlotDTO]: ...
    @staticmethod
    def read(pk: int) -> TimeSlotDTO: ...
    @staticmethod
    def read_by_event(event_id: int, pk: int) -> TimeSlotDTO: ...
    @staticmethod
    def update(pk: int, start_time: datetime, end_time: datetime) -> TimeSlotDTO: ...


class EventProposalSettingsRepositoryProtocol(Protocol):
    @staticmethod
    def read_or_create_by_event(event_id: int) -> EventProposalSettingsDTO: ...

    @staticmethod
    def read_by_event(event_id: int) -> EventProposalSettingsDTO: ...

    @staticmethod
    def update_allow_anonymous_proposals(event_id: int, *, allow: bool) -> None: ...

    @staticmethod
    def update_description(event_id: int, description: str) -> None: ...


class EventsRepositoryProtocol(EventRepositoryProtocol, Protocol):
    @staticmethod
    def create(sphere_id: int, data: EventCreateData) -> EventDTO: ...
    @staticmethod
    def read_in_sphere(pk: int, sphere_id: int) -> EventDTO: ...
    @staticmethod
    def slug_exists(sphere_id: int, slug: str) -> bool: ...


class EventSetupRepositoryProtocol(Protocol):
    @staticmethod
    def copy(*, source_id: int, target_id: int, start_time: datetime) -> None: ...


class EventsServiceProtocol(Protocol):
    def list_for_sphere(
        self, sphere_id: int, *, include_hidden: bool
    ) -> list[EventListItemDTO]: ...
    def read_by_slug(self, sphere_id: int, slug: str) -> EventDTO: ...
    def require_in_sphere(self, *, sphere_id: int, event_id: int) -> EventDTO: ...
    def create(
        self, *, sphere_id: int, data: EventCreateData, based_on_id: int | None = None
    ) -> EventDTO: ...


class FacilitatorListItemDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    accreditation_type: str
    deleted_at: datetime | None = None
    display_name: str
    # Attached by the panel view, not the ORM. Null means no guild.
    guild: GuildMarkDTO | None = None
    organizer_id: int | None
    # Annotated by the list queries; null when nobody took the facilitator on.
    organizer_name: str | None
    pk: int
    session_count: int
    slug: str
    user_id: int | None


class TimeSlotValidationError(StrEnum):
    START_NOT_BEFORE_END = "start_not_before_end"
    OVERLAPS_EXISTING_SLOT = "overlaps_existing_slot"
    STARTS_BEFORE_PUBLICATION = "starts_before_publication"


class TimeSlotRejectedError(Exception):
    def __init__(self, errors: list[TimeSlotValidationError]) -> None:
        super().__init__(", ".join(error.value for error in errors))
        self.errors = errors


class TimeSlotSavedDTO(BaseModel):
    slot: TimeSlotDTO
    event_dates_widened: bool


class EventPanelContextDTO(BaseModel):
    events: list[EventDTO]
    current_event: EventDTO
    is_proposal_active: bool
    stats: PanelStatsDTO


class EventPanelServiceProtocol(Protocol):
    def load_context(
        self, *, sphere_id: int, current_event: EventDTO
    ) -> EventPanelContextDTO: ...


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
    # Only a placed session has a schedule to confirm, so the template hangs
    # the checkbox off this.
    is_scheduled: bool
    is_confirmed: bool
    co_facilitator_names: list[str]
    other_track_names: list[str]


class ConfirmationStatusGroupDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: SessionStatus
    is_scheduled: bool
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
        session_pk: int | None = None,
    ) -> None: ...


class PanelTimeSlotsServiceProtocol(Protocol):
    def list_for_event(self, event_id: int) -> list[TimeSlotDTO]: ...
    def undeletable_pks(self, event_id: int) -> frozenset[int]: ...
    def read(self, *, event_id: int, pk: int) -> TimeSlotDTO: ...
    def create(
        self, *, event: EventDTO, start_time: datetime, end_time: datetime
    ) -> TimeSlotSavedDTO: ...
    def update(
        self, *, event: EventDTO, pk: int, start_time: datetime, end_time: datetime
    ) -> TimeSlotSavedDTO: ...
    def delete(self, *, event_id: int, pk: int) -> bool: ...


class LandingStatsDTO(BaseModel):
    events: int
    sessions: int


class LandingConventionDTO(BaseModel):
    """A convention to show on the landing, with its newest event and cover."""

    name: str
    domain: str
    event_slug: str
    cover_image_url: str


class LandingStatsRepositoryProtocol(Protocol):
    @staticmethod
    def count_landing_stats() -> LandingStatsDTO: ...
    @staticmethod
    def list_conventions(domains: tuple[str, ...]) -> list[LandingConventionDTO]: ...
    @staticmethod
    def read_newest_published_slug(sphere_id: int) -> str | None: ...


class LandingServiceProtocol(Protocol):
    def stats(self) -> LandingStatsDTO: ...
    def conventions(self) -> list[LandingConventionDTO]: ...
    def showcase_slug(self, sphere_id: int) -> str | None: ...
