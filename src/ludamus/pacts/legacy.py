from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum, auto
from typing import (
    TYPE_CHECKING,
    Literal,
    NotRequired,
    Protocol,
    TypedDict,
    runtime_checkable,
)

from pydantic import BaseModel, ConfigDict

from ludamus.pacts.fields import OrganizerFieldDTO

if TYPE_CHECKING:
    from collections.abc import Iterable
    from contextlib import AbstractContextManager

    from ludamus.pacts.crowd import (
        CompanionRepositoryProtocol,
        UserDTO,
        UserRepositoryProtocol,
    )
    from ludamus.pacts.event import FacilitatorListItemDTO
    from ludamus.pacts.services import ServicesProtocol
    from ludamus.pacts.submissions import FacilitatorListFilters


class NotFoundError(Exception):
    pass


class RedirectError(Exception):
    def __init__(
        self, url: str, *, error: str | None = None, warning: str | None = None
    ) -> None:
        self.url = url
        self.error = error
        self.warning = warning


class DateTimeRangeProtocol(Protocol):
    """Protocol for objects with start_time and end_time datetime fields."""

    start_time: datetime
    end_time: datetime


@runtime_checkable
class UploadedFileProtocol(Protocol):
    name: str | None

    def read(self, size: int = -1) -> bytes: ...


def parse_uploaded_file(value: object) -> UploadedFileProtocol | None:
    # Boundary parser: recover a typed upload from the untyped form-data value
    # (a file on upload, "" / False / None otherwise), so callers narrow once
    # here instead of casting.
    return value if isinstance(value, UploadedFileProtocol) else None


def resolve_uploaded_file_field(raw: object) -> UploadedFileProtocol | str | None:
    # ClearableFileInput's tri-state in one place: a file on upload becomes the
    # new value, False clears it (""), and any other value (None / unchanged)
    # returns None so the caller leaves the stored file untouched.
    if uploaded := parse_uploaded_file(raw):
        return uploaded
    return "" if raw is False else None


class FacilitatorDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    accreditation_type: str
    display_name: str
    event_id: int
    guild_id: int | None = None
    ident: str = ""
    internal_comment: str = ""
    organizer_id: int | None = None
    # Annotated by the single-facilitator reads, so a page showing the
    # organizer needs no second lookup. `create` and `update` return the row
    # they just wrote, without it.
    organizer_name: str | None = None
    pk: int
    slug: str
    user_id: int | None


class FacilitatorData(TypedDict, total=False):
    accreditation_type: str
    display_name: str
    event_id: int
    ident: str
    organizer_id: int | None
    slug: str
    user_id: int | None


class FacilitatorUpdateData(TypedDict, total=False):
    accreditation_type: str
    display_name: str
    guild_id: int | None
    internal_comment: str
    organizer_id: int | None
    user_id: int | None


class PromotionMode(StrEnum):
    AUTO = auto()
    OFFER_CLAIM = auto()


class ProposalCategoryDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    description: str
    durations: list[str]
    end_time: datetime | None
    max_participants_limit: int
    min_participants_limit: int
    name: str
    offer_claim_window: timedelta = timedelta(hours=24)
    pk: int
    promotion_mode: PromotionMode = PromotionMode.AUTO
    slug: str
    start_time: datetime | None


class SessionFieldValueDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    allow_custom: bool = False
    field_icon: str = ""
    field_id: int = 0
    field_name: str
    field_question: str
    field_slug: str = ""
    field_order: int = 0
    field_type: str = "text"
    is_public: bool = False
    value: str | list[str] | bool


UNSCHEDULED_LIST_LIMIT = 20


class UnscheduledSessionDTO(BaseModel):
    """Session accepted but not yet placed in the timetable."""

    pk: int
    title: str
    display_name: str
    category_name: str
    category_pk: int | None
    duration_minutes: int
    participants_limit: int


class UnscheduledSessionFilter(BaseModel):
    track_pk: int | None = None
    search: str | None = None
    max_duration_minutes: int | None = None
    category_pk: int | None = None
    available_on: date | None = None
    facilitator_pks: set[int] = set()


class SessionListItemDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    category_name: str
    creation_time: datetime
    display_name: str
    is_scheduled: bool
    pk: int
    status: "SessionStatus"
    title: str


class AgendaItemDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    end_time: datetime
    pk: int
    session_confirmed: bool
    start_time: datetime
    space_id: int = 0
    space_name: str = ""
    session_id: int = 0
    session_title: str = ""
    session_description: str = ""
    presenter_name: str = ""
    session_duration_minutes: int = 0
    session_status: "SessionStatus | None" = None
    category_name: str | None = None


class SessionDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    category_id: int | None
    contact_email: str
    creation_time: datetime
    description: str
    duration: str = ""
    min_age: int
    modification_time: datetime
    participants_limit: int
    pk: int
    presenter_id: int | None
    display_name: str
    slug: str
    status: SessionStatus
    title: str
    cover_image_url: str = ""
    cover_image_original_name: str = ""


class PendingSessionTimeSlotDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    end_time: datetime
    pk: int
    start_time: datetime


class PendingSessionDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    contact_email: str
    creation_time: datetime
    description: str
    participants_limit: int
    pk: int
    display_name: str
    time_slots: list[PendingSessionTimeSlotDTO]
    title: str


class LocationData(TypedDict):
    # Tree location of a scheduled leaf: its name, its immediate parent (the
    # grouping unit, empty for a root leaf), and the full "Root > ... > Leaf"
    # path used as a display label.
    space_name: str
    parent_slug: str
    parent_name: str
    path: str


class SessionStatus(StrEnum):
    PENDING = auto()
    ACCEPTED = auto()
    ON_HOLD = auto()
    REJECTED = auto()


class SessionListFilters(TypedDict, total=False):
    field_filters: dict[int, str] | None
    search: str | None
    track_pk: int | None
    multi_tracks: bool | None
    category_pk: int | None
    status: SessionStatus | None
    scheduled: bool | None
    sort: str | None


class SessionParticipationStatus(StrEnum):
    CONFIRMED = auto()
    WAITING = auto()
    OFFERED = auto()


# Statuses that occupy (hold) a seat against a session's capacity. An OFFERED
# seat is held so the same seat is never offered to two waiters at once.
OCCUPYING_PARTICIPATION_STATUSES = (
    SessionParticipationStatus.CONFIRMED,
    SessionParticipationStatus.OFFERED,
)


class NotificationKind(StrEnum):
    WAITLIST_PROMOTED = auto()
    WAITLIST_OFFER = auto()
    OFFER_EXPIRED = auto()
    SHADOWBANNED_SIGNUP = auto()
    PARTY_INVITE = auto()
    PARTY_ENROLLED = auto()
    PARTY_SEAT_HELD = auto()
    PRINTABLES_READY = auto()


class SpherePage(StrEnum):
    EVENTS = "events"
    ENCOUNTERS = "encounters"

    @classmethod
    def all_values(cls) -> list[str]:
        return [p.value for p in cls]


class SpaceDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    parent_id: int | None = None
    capacity: int | None
    creation_time: datetime
    modification_time: datetime
    name: str
    order: int
    pk: int
    slug: str


class SpaceOptionDTO(BaseModel):
    # A bookable leaf space as a form choice: its pk, display name, and the
    # immediate-parent name it groups under (empty for a root-level leaf).
    pk: int
    name: str
    group: str


class TrackDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    creation_time: datetime
    event_id: int
    is_public: bool
    modification_time: datetime
    name: str
    pk: int
    slug: str


class TrackListItemDTO(BaseModel):
    # Track enriched with the names of its assigned spaces and managers, for the
    # panel list view. Names, not pks, so the template renders without extra IO.
    pk: int
    name: str
    slug: str
    is_public: bool
    space_names: list[str]
    manager_names: list[str]


class TrackSessionCountsDTO(BaseModel):
    # A track's sessions-per-status breakdown, plus how many accepted ones are
    # placed on the agenda. Feeds the overview progress bars without loading
    # session rows.
    pending: int = 0
    accepted: int = 0
    scheduled: int = 0
    on_hold: int = 0
    rejected: int = 0


class TrackCreateData(TypedDict):
    event_pk: int
    name: str
    is_public: bool
    space_pks: list[int]
    manager_pks: list[int]


class TrackUpdateData(TypedDict):
    name: str
    is_public: bool
    space_pks: list[int]
    manager_pks: list[int]


class TimeSlotDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    end_time: datetime
    pk: int
    start_time: datetime


class SessionData(TypedDict, total=False):
    category_id: int | None
    contact_email: str
    cover_image: UploadedFileProtocol
    description: str
    duration: str
    event_id: int
    ident: str
    min_age: int
    participants_limit: int
    presenter_id: int | None
    display_name: str
    slug: str
    status: SessionStatus
    title: str


class SessionUpdateData(TypedDict, total=False):
    category_id: int | None
    contact_email: str
    cover_image: UploadedFileProtocol | str
    description: str
    display_name: str
    duration: str
    min_age: int
    participants_limit: int
    slug: str
    status: SessionStatus
    title: str


class AgendaItemData(TypedDict):
    end_time: datetime
    session_confirmed: bool
    session_id: int
    space_id: int
    start_time: datetime


class AgendaItemUpdateData(TypedDict, total=False):
    end_time: datetime
    session_confirmed: bool
    space_id: int
    start_time: datetime


class SiteDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    domain: str
    name: str
    pk: int


class SphereDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    allow_facilitator_session_edit: bool = True
    default_page: SpherePage
    enabled_pages: list[SpherePage]
    name: str
    pk: int
    site: SiteDTO
    logo_url: str = ""
    logo_original_name: str = ""


class SphereUpdateData(TypedDict, total=False):
    allow_facilitator_session_edit: bool
    logo: UploadedFileProtocol | str


@dataclass
class SessionSelfEditContext:
    session: SessionDTO
    event: EventDTO
    session_fields: list[tuple[OrganizerFieldDTO, str | list[str] | bool | None]]
    facilitators: list[FacilitatorDTO]


class EventDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    allow_facilitator_session_edit: bool | None = None
    auto_confirm_sessions: bool = False
    description: str
    end_time: datetime
    name: str
    pk: int
    proposal_end_time: datetime | None
    proposal_start_time: datetime | None
    publication_time: datetime | None
    slug: str
    sphere_id: int
    start_time: datetime
    use_session_cover_placeholders: bool = False
    use_participants_label: bool = False
    cover_image_url: str = ""
    cover_image_original_name: str = ""
    logo_url: str = ""
    logo_original_name: str = ""


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


class EncounterDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    creation_time: datetime
    creator_id: int
    description: str
    end_time: datetime | None
    game: str
    max_participants: int
    pk: int
    place: str
    share_code: str
    sphere_id: int
    start_time: datetime
    title: str
    header_image_url: str = ""
    header_image_original_name: str = ""


class EncounterRSVPDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    creation_time: datetime
    encounter_id: int
    ip_address: str
    pk: int
    user_id: int


class EncounterData(TypedDict, total=False):
    creator_id: int
    description: str
    end_time: datetime | None
    game: str
    header_image: UploadedFileProtocol | str
    max_participants: int
    place: str
    share_code: str
    sphere_id: int
    start_time: datetime
    title: str


@dataclass
class EncounterDetailResult:  # pylint: disable=too-many-instance-attributes
    encounter: EncounterDTO
    creator: UserDTO
    rsvps: list[EncounterRSVPDTO]
    rsvp_count: int
    is_full: bool
    spots_remaining: int | None
    is_creator: bool
    user_has_rsvpd: bool


@dataclass
class EncounterIndexItem:
    encounter: EncounterDTO
    rsvp_count: int
    is_mine: bool
    organizer_name: str


@dataclass
class EncounterIndexResult:
    upcoming: list[EncounterIndexItem]
    past: list[EncounterIndexItem]


class EnrollmentConfigDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    allow_anonymous_enrollment: bool
    banner_text: str
    end_time: datetime
    event_id: int
    limit_to_end_time: bool
    max_waitlist_sessions: int
    percentage_slots: int
    pk: int
    restrict_to_configured_users: bool
    start_time: datetime


class ProposalCategoryData(TypedDict, total=False):
    description: str
    durations: list[str]
    end_time: datetime | None
    max_participants_limit: int
    min_participants_limit: int
    name: str
    offer_claim_window: timedelta
    promotion_mode: PromotionMode
    start_time: datetime | None


class CategoryStats(TypedDict):
    """Statistics for a proposal category."""

    proposals_count: int
    accepted_count: int


class EventProposalSettingsDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    allow_anonymous_proposals: bool
    description: str
    pk: int


class EventSettingsDTO(BaseModel):
    """Display settings for an event."""

    model_config = ConfigDict(from_attributes=True)

    displayed_session_field_ids: list[int] = []
    pk: int


class EventUpdateData(TypedDict, total=False):
    """Write shape for updating event fields."""

    name: str
    slug: str
    description: str
    logo: UploadedFileProtocol | str
    cover_image: UploadedFileProtocol | str
    start_time: datetime
    end_time: datetime
    publication_time: datetime | None
    proposal_start_time: datetime | None
    proposal_end_time: datetime | None
    allow_facilitator_session_edit: bool | None
    auto_confirm_sessions: bool
    use_session_cover_placeholders: bool
    use_participants_label: bool


@dataclass
class FieldUsageSummary:
    """A field DTO bundled with its usage counts across categories."""

    field: OrganizerFieldDTO
    required_count: int
    optional_count: int


class PersonalFieldRequirementDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    field: OrganizerFieldDTO
    is_required: bool


class SessionFieldRequirementDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    field: OrganizerFieldDTO
    is_required: bool


class TimeSlotRequirementDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    time_slot: TimeSlotDTO
    time_slot_id: int
    is_required: bool


class SessionFieldValueData(TypedDict):
    session_id: int
    field_id: int
    value: str | list[str] | bool


class PersonalDataFieldValueData(TypedDict):
    facilitator_id: int
    event_id: int
    field_id: int
    value: str | list[str] | bool


class WizardData(TypedDict, total=False):
    category_id: int
    contact_email: str
    personal_data: dict[str, str]
    session_data: dict[str, object]
    time_slot_ids: list[int]
    track_pks: list[int]


@dataclass
class ProposeSessionResult:
    session_id: int
    title: str


@dataclass
class RequestContext:
    current_site_id: int
    current_sphere_id: int
    root_site_id: int
    root_sphere_id: int
    current_user_slug: str | None = None
    current_user_id: int | None = None


@dataclass
class AuthenticatedRequestContext(RequestContext):
    current_user_slug: str
    current_user_id: int


class PanelStatsDTO(BaseModel):
    """Statistics for the backoffice panel dashboard."""

    model_config = ConfigDict(from_attributes=True)

    hosts_count: int = 0
    pending_proposals: int = 0
    rooms_count: int = 0
    scheduled_sessions: int = 0
    total_proposals: int = 0
    total_sessions: int = 0


class UserEnrollmentConfigDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    allowed_slots: int
    enrollment_config_id: int
    fetched_from_api: bool
    last_check: datetime | None
    pk: int
    user_email: str


class DomainEnrollmentConfigDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pk: int
    enrollment_config_id: int
    domain: str
    allowed_slots_per_user: int


class EventStatsData(BaseModel):
    """Raw statistics data from the repository."""

    model_config = ConfigDict(from_attributes=True)

    pending_proposals: int
    scheduled_sessions: int
    total_proposals: int
    hosts_count: int
    rooms_count: int


class SphereRepositoryProtocol(Protocol):
    @staticmethod
    def read_by_domain(domain: str) -> SphereDTO: ...
    @staticmethod
    def read(pk: int) -> SphereDTO: ...
    @staticmethod
    def is_manager(sphere_id: int, user_slug: str) -> bool: ...
    @staticmethod
    def list_managers(sphere_id: int) -> list[UserDTO]: ...
    @staticmethod
    def update(sphere_id: int, data: SphereUpdateData) -> None: ...


class SessionRepositoryProtocol(Protocol):
    @staticmethod
    def create(
        session_data: SessionData,
        *,
        time_slot_ids: Iterable[int] = (),
        facilitator_ids: Iterable[int] = (),
        track_ids: Iterable[int] = (),
    ) -> int: ...
    @staticmethod
    def read(pk: int) -> SessionDTO: ...
    @staticmethod
    def read_by_event(pk: int, event_id: int) -> SessionDTO: ...
    @staticmethod
    def read_presenter(session_id: int) -> UserDTO | None: ...
    @staticmethod
    def list_confirmation_rows(
        event_pk: int, facilitator_pks: list[int]
    ) -> list[ConfirmationSessionRow]: ...
    @staticmethod
    def list_track_names_by_session(
        session_pks: list[int],
    ) -> dict[int, dict[int, str]]: ...
    @staticmethod
    def list_facilitator_names_by_session(
        session_pks: list[int],
    ) -> dict[int, dict[int, str]]: ...
    @staticmethod
    def lock(pk: int) -> None: ...
    @staticmethod
    def update(pk: int, data: SessionUpdateData) -> None: ...
    @staticmethod
    def soft_delete(pk: int) -> None: ...
    @staticmethod
    def restore(pk: int, event_pk: int) -> None: ...
    @staticmethod
    def list_deleted_by_event(event_pk: int) -> list[SessionListItemDTO]: ...
    @staticmethod
    def list_by_facilitator(facilitator_id: int) -> list[SessionListItemDTO]: ...
    @staticmethod
    def read_event(session_id: int) -> EventDTO: ...
    @staticmethod
    def read_space_options(session_id: int) -> list[SpaceOptionDTO]: ...
    @staticmethod
    def read_time_slot(session_id: int, time_slot_id: int) -> TimeSlotDTO: ...
    @staticmethod
    def read_time_slots(session_id: int) -> list[TimeSlotDTO]: ...
    @staticmethod
    def count_by_category(category_id: int) -> int: ...
    @staticmethod
    def read_pending_by_event(event_id: int) -> list[PendingSessionDTO]: ...
    @staticmethod
    def read_preferred_time_slot_ids(session_id: int) -> list[int]: ...
    @staticmethod
    def read_preferred_time_slots(session_id: int) -> list[TimeSlotDTO]: ...
    @staticmethod
    def read_preferred_time_slots_by_sessions(
        session_ids: Iterable[int],
    ) -> dict[int, list[TimeSlotDTO]]: ...
    @staticmethod
    def slug_exists(event_id: int, slug: str) -> bool: ...
    @staticmethod
    def find_id_by_ident(event_id: int, ident: str) -> int | None: ...
    @staticmethod
    def find_ids_by_title_and_email(
        *, event_id: int, title: str, contact_email: str
    ) -> list[int]: ...
    @staticmethod
    def set_ident(pk: int, ident: str) -> None: ...
    @staticmethod
    def save_field_values(
        session_id: int, values: list[SessionFieldValueData]
    ) -> None: ...
    @staticmethod
    def read_field_values(session_id: int) -> list[SessionFieldValueDTO]: ...
    @staticmethod
    def list_field_values_for_sessions(
        session_ids: list[int], field_ids: list[int]
    ) -> dict[int, dict[str, str | list[str] | bool]]: ...
    @staticmethod
    def delete_field_values_for_fields(
        session_id: int, field_ids: list[int]
    ) -> int: ...
    @staticmethod
    def list_sessions_by_event(
        event_id: int, filters: SessionListFilters | None = None
    ) -> list[SessionListItemDTO]: ...
    @staticmethod
    def read_track_ids(session_id: int) -> list[int]: ...
    @staticmethod
    def read_tracks(session_id: int) -> list[TrackDTO]: ...
    @staticmethod
    def set_session_tracks(session_pk: int, track_pks: list[int]) -> None: ...
    @staticmethod
    def set_time_slots(session_id: int, time_slot_ids: list[int]) -> None: ...
    @staticmethod
    def read_facilitators(session_id: int) -> list[FacilitatorDTO]: ...
    @staticmethod
    def read_facilitators_by_sessions(
        session_ids: Iterable[int],
    ) -> dict[int, list[FacilitatorDTO]]: ...
    @staticmethod
    def read_participants_limits(session_ids: Iterable[int]) -> dict[int, int]: ...
    @staticmethod
    def count_by_track(event_id: int) -> dict[int, TrackSessionCountsDTO]: ...
    @staticmethod
    def set_facilitators(session_id: int, facilitator_ids: list[int]) -> None: ...
    @staticmethod
    def replace_facilitators_in_sessions(
        source_ids: list[int], target_id: int
    ) -> None: ...
    @staticmethod
    def list_unscheduled_by_event(
        event_pk: int, filters: UnscheduledSessionFilter
    ) -> tuple[list[UnscheduledSessionDTO], bool]: ...


class TrackRepositoryProtocol(Protocol):
    def create(self, data: TrackCreateData) -> TrackDTO: ...
    @staticmethod
    def get_or_create_by_slug(event_id: int, name: str, slug: str) -> int: ...
    @staticmethod
    def read(pk: int) -> TrackDTO: ...
    @staticmethod
    def read_by_slug(event_pk: int, slug: str) -> TrackDTO: ...
    def update(self, pk: int, data: TrackUpdateData) -> TrackDTO: ...
    @staticmethod
    def delete(pk: int) -> None: ...
    @staticmethod
    def list_by_event(event_pk: int) -> list[TrackDTO]: ...
    @staticmethod
    def list_by_event_with_assignments(event_pk: int) -> list[TrackListItemDTO]: ...
    @staticmethod
    def list_public_by_event(event_pk: int) -> list[TrackDTO]: ...
    @staticmethod
    def list_by_manager(
        user_pk: int, event_pk: int | None = None
    ) -> list[TrackDTO]: ...
    @staticmethod
    def list_space_pks(pk: int) -> list[int]: ...
    @staticmethod
    def list_manager_pks(pk: int) -> list[int]: ...
    @staticmethod
    def list_manager_names_by_event(event_pk: int) -> dict[int, list[str]]: ...
    @staticmethod
    def list_manager_names_by_tracks(
        track_pks: Iterable[int],
    ) -> dict[int, list[str]]: ...


class ConfirmationCountsRow(TypedDict):
    """One aggregate row: who or what, and its confirmed-of-scheduled counts.

    `key` is the grouping id — organizer id (None when nobody claimed the
    facilitators) or track pk.
    """

    key: int | None
    name: str
    facilitator_count: int
    scheduled_count: int
    confirmed_count: int


class ConfirmationTotalsRow(TypedDict):
    scheduled_count: int
    confirmed_count: int


class ConfirmationFacilitatorRow(TypedDict):
    pk: int
    display_name: str
    slug: str
    organizer_id: int | None
    organizer_name: str


class ConfirmationSessionRow(TypedDict):
    """One (facilitator, session) pair, flattened for the confirmations page.

    Agenda-item columns are None for a session with no place in the timetable.
    """

    facilitator_pk: int
    session_pk: int
    title: str
    status: SessionStatus
    contact_email: str
    category_name: str
    agenda_item_pk: int | None
    is_confirmed: bool
    start_time: datetime | None
    end_time: datetime | None
    room_name: str


class AgendaItemRepositoryProtocol(Protocol):
    @staticmethod
    def create(agenda_item_data: AgendaItemData) -> None: ...
    @staticmethod
    def read(pk: int) -> AgendaItemDTO: ...
    @staticmethod
    def list_by_event(
        event_pk: int, *, facilitator_pks: set[int] | None = None
    ) -> list[AgendaItemDTO]: ...
    @staticmethod
    def list_by_track(
        track_pk: int, *, facilitator_pks: set[int] | None = None
    ) -> list[AgendaItemDTO]: ...
    @staticmethod
    def read_by_session(session_pk: int) -> AgendaItemDTO | None: ...
    @staticmethod
    def list_overlapping_in_space(
        space_pk: int,
        start_time: datetime,
        end_time: datetime,
        exclude_session_pk: int | None = None,
    ) -> list[AgendaItemDTO]: ...
    @staticmethod
    def update(pk: int, data: AgendaItemUpdateData) -> None: ...
    @staticmethod
    def count_confirmations_by_track(event_pk: int) -> list[ConfirmationCountsRow]: ...
    @staticmethod
    def count_event_totals(event_pk: int) -> ConfirmationTotalsRow: ...
    @staticmethod
    def set_confirmed_for_facilitator(
        *,
        event_pk: int,
        facilitator_pk: int,
        confirmed: bool,
        contact_email: str | None = None,
        agenda_item_pk: int | None = None,
    ) -> int: ...
    @staticmethod
    def count_without_facilitator(
        event_pk: int, track_pk: int | None = None
    ) -> int: ...
    @staticmethod
    def delete(pk: int) -> None: ...


class EventRepositoryProtocol(Protocol):
    @staticmethod
    def list_by_sphere(sphere_id: int) -> list[EventDTO]: ...
    @staticmethod
    def list_for_events_page(
        sphere_id: int, *, include_unpublished: bool
    ) -> list[EventListItemDTO]: ...
    @staticmethod
    def read(pk: int) -> EventDTO: ...
    @staticmethod
    def read_by_slug(slug: str, sphere_id: int) -> EventDTO: ...
    @staticmethod
    def get_stats_data(event_id: int) -> EventStatsData: ...
    @staticmethod
    def update(event_id: int, data: EventUpdateData) -> None: ...


class SpaceRepositoryProtocol(Protocol):
    @staticmethod
    def read(pk: int) -> SpaceDTO: ...
    @staticmethod
    def delete(pk: int) -> None: ...
    @staticmethod
    def list_by_event(event_pk: int) -> list[SpaceDTO]: ...
    @staticmethod
    def lock(pk: int) -> None: ...


class ProposalCategoryRepositoryProtocol(Protocol):
    def create(self, event_id: int, name: str) -> ProposalCategoryDTO: ...
    @staticmethod
    def get_or_create_by_slug(event_id: int, name: str, slug: str) -> int: ...
    @staticmethod
    def delete(pk: int) -> None: ...
    @staticmethod
    def get_category_stats(event_id: int) -> dict[int, CategoryStats]: ...
    @staticmethod
    def get_field_order(category_id: int) -> list[int]: ...
    @staticmethod
    def get_field_requirements(category_id: int) -> dict[int, bool]: ...
    @staticmethod
    def get_session_field_order(category_id: int) -> list[int]: ...
    @staticmethod
    def get_session_field_requirements(category_id: int) -> dict[int, bool]: ...
    @staticmethod
    def has_proposals(pk: int) -> bool: ...
    @staticmethod
    def list_by_event(event_id: int) -> list[ProposalCategoryDTO]: ...
    @staticmethod
    def read(pk: int, event_id: int) -> ProposalCategoryDTO: ...
    @staticmethod
    def read_by_slug(event_id: int, slug: str) -> ProposalCategoryDTO: ...
    @staticmethod
    def list_personal_field_requirements(
        category_id: int,
    ) -> list[PersonalFieldRequirementDTO]: ...
    @staticmethod
    def list_session_field_requirements(
        category_id: int,
    ) -> list[SessionFieldRequirementDTO]: ...
    @staticmethod
    def list_time_slot_requirements(
        category_id: int,
    ) -> list[TimeSlotRequirementDTO]: ...
    @staticmethod
    def set_field_requirements(
        category_id: int, requirements: dict[int, bool], order: list[int] | None = None
    ) -> None: ...
    @staticmethod
    def set_session_field_requirements(
        category_id: int, requirements: dict[int, bool], order: list[int] | None = None
    ) -> None: ...
    @staticmethod
    def get_time_slot_requirements(category_id: int) -> dict[int, bool]: ...
    @staticmethod
    def get_time_slot_order(category_id: int) -> list[int]: ...
    @staticmethod
    def set_time_slot_requirements(
        category_id: int, requirements: dict[int, bool], order: list[int] | None = None
    ) -> None: ...
    @staticmethod
    def get_personal_field_categories(field_id: int) -> dict[int, bool]: ...
    @staticmethod
    def set_personal_field_categories(
        field_id: int, categories: dict[int, bool]
    ) -> None: ...
    @staticmethod
    def get_session_field_categories(field_id: int) -> dict[int, bool]: ...
    @staticmethod
    def set_session_field_categories(
        field_id: int, categories: dict[int, bool]
    ) -> None: ...
    def update(self, pk: int, data: ProposalCategoryData) -> ProposalCategoryDTO: ...


class PersonalDataFieldCreateData(TypedDict):
    name: str
    slug: NotRequired[str]
    question: str
    field_type: Literal["text", "select", "checkbox"]
    options: list[str] | None
    is_multiple: bool
    allow_custom: bool
    max_length: int
    help_text: str
    is_public: bool


class PersonalDataFieldUpdateData(TypedDict):
    name: str
    question: str
    max_length: int
    help_text: str
    is_public: bool
    options: list[str] | None
    is_multiple: bool
    allow_custom: bool


class SessionFieldCreateData(TypedDict):
    name: str
    slug: NotRequired[str]
    question: str
    field_type: Literal["text", "select", "checkbox"]
    options: list[str] | None
    is_multiple: bool
    allow_custom: bool
    max_length: int
    help_text: str
    icon: str
    is_public: bool


class SessionFieldUpdateData(TypedDict):
    name: str
    question: str
    max_length: int
    help_text: str
    icon: str
    is_public: bool
    options: list[str] | None
    is_multiple: bool
    allow_custom: bool


class PersonalDataFieldRepositoryProtocol(Protocol):
    def create(
        self, event_id: int, data: PersonalDataFieldCreateData
    ) -> OrganizerFieldDTO: ...
    @staticmethod
    def delete(pk: int) -> None: ...
    @staticmethod
    def delete_orphans_for_event(event_id: int) -> int: ...
    @staticmethod
    def has_requirements(pk: int) -> bool: ...
    @staticmethod
    def get_usage_counts(event_id: int) -> dict[int, dict[str, int]]: ...
    def list_by_event(self, event_id: int) -> list[OrganizerFieldDTO]: ...
    def read_by_slug(self, event_id: int, slug: str) -> OrganizerFieldDTO: ...
    def update(
        self, pk: int, data: PersonalDataFieldUpdateData
    ) -> OrganizerFieldDTO: ...


class SessionFieldRepositoryProtocol(Protocol):
    def create(
        self, event_id: int, data: SessionFieldCreateData
    ) -> OrganizerFieldDTO: ...
    @staticmethod
    def delete(pk: int) -> None: ...
    @staticmethod
    def delete_orphans_for_event(event_id: int) -> int: ...
    @staticmethod
    def has_requirements(pk: int) -> bool: ...
    @staticmethod
    def get_usage_counts(event_id: int) -> dict[int, dict[str, int]]: ...
    def list_by_event(self, event_id: int) -> list[OrganizerFieldDTO]: ...
    def read_by_slug(self, event_id: int, slug: str) -> OrganizerFieldDTO: ...
    def update(self, pk: int, data: SessionFieldUpdateData) -> OrganizerFieldDTO: ...


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


class EventSettingsRepositoryProtocol(Protocol):
    @staticmethod
    def read_or_create(event_id: int) -> EventSettingsDTO: ...
    @staticmethod
    def update_displayed_fields(event_id: int, field_ids: list[int]) -> None: ...


class EnrollmentConfigRepositoryProtocol(Protocol):
    @staticmethod
    def read_list(
        event_id: int, max_start_time: datetime, min_end_time: datetime
    ) -> list[EnrollmentConfigDTO]: ...
    @staticmethod
    def create_user_config(
        user_enrollment_config: UserEnrollmentConfigData,
    ) -> UserEnrollmentConfigDTO: ...
    @staticmethod
    def read_user_config(
        config: EnrollmentConfigDTO, user_email: str
    ) -> UserEnrollmentConfigDTO | None: ...
    @staticmethod
    def update_user_config(user_enrollment_config: UserEnrollmentConfigDTO) -> None: ...
    @staticmethod
    def read_domain_config(
        enrollment_config: EnrollmentConfigDTO, domain: str
    ) -> DomainEnrollmentConfigDTO | None: ...


class EncounterRepositoryProtocol(Protocol):
    @staticmethod
    def create(data: EncounterData) -> EncounterDTO: ...
    @staticmethod
    def read(pk: int) -> EncounterDTO: ...
    @staticmethod
    def read_by_share_code(share_code: str) -> EncounterDTO: ...
    @staticmethod
    def list_upcoming_by_creator(
        sphere_id: int, creator_id: int
    ) -> list[EncounterDTO]: ...
    @staticmethod
    def list_upcoming_rsvpd(sphere_id: int, user_id: int) -> list[EncounterDTO]: ...
    @staticmethod
    def list_past(sphere_id: int, user_id: int) -> list[EncounterDTO]: ...
    @staticmethod
    def update(pk: int, data: EncounterData) -> None: ...
    @staticmethod
    def delete(pk: int) -> None: ...


class EncounterRSVPRepositoryProtocol(Protocol):
    @staticmethod
    def create(
        encounter_id: int, ip_address: str, user_id: int
    ) -> EncounterRSVPDTO: ...
    @staticmethod
    def list_by_encounter(encounter_id: int) -> list[EncounterRSVPDTO]: ...
    @staticmethod
    def count_by_encounter(encounter_id: int) -> int: ...
    @staticmethod
    def recent_rsvp_exists(ip_address: str, seconds: int = 60) -> bool: ...
    @staticmethod
    def user_has_rsvpd(encounter_id: int, user_id: int) -> bool: ...
    @staticmethod
    def delete_by_user(encounter_id: int, user_id: int) -> None: ...


class FacilitatorRepositoryProtocol(Protocol):
    @staticmethod
    def create(data: FacilitatorData) -> FacilitatorDTO: ...
    @staticmethod
    def read(pk: int) -> FacilitatorDTO: ...
    @staticmethod
    def read_by_event_and_slug(event_id: int, slug: str) -> FacilitatorDTO: ...
    @staticmethod
    def read_by_user_and_event(user_id: int, event_id: int) -> FacilitatorDTO: ...
    @staticmethod
    def find_id_by_ident(event_id: int, ident: str) -> int | None: ...
    @staticmethod
    def set_ident(pk: int, ident: str) -> None: ...
    @staticmethod
    def update(pk: int, data: FacilitatorUpdateData) -> FacilitatorDTO: ...
    @staticmethod
    def list_by_event(
        event_id: int, filters: FacilitatorListFilters | None = None
    ) -> list[FacilitatorListItemDTO]: ...
    @staticmethod
    def list_by_slugs(
        event_id: int, facilitator_slugs: list[str]
    ) -> list[FacilitatorListItemDTO]: ...
    @staticmethod
    def set_flag(pk: int, *, flagged: bool) -> None: ...
    @staticmethod
    def claim(pk: int, organizer_id: int) -> bool: ...
    @staticmethod
    def release(pk: int, *, organizer_id: int | None) -> bool: ...
    @staticmethod
    def count_confirmations_by_organizer(
        event_pk: int,
    ) -> list[ConfirmationCountsRow]: ...
    @staticmethod
    def list_with_scheduled_session_in_track(
        event_pk: int, track_pk: int
    ) -> list[ConfirmationFacilitatorRow]: ...
    @staticmethod
    def delete(pk: int) -> None: ...
    @staticmethod
    def slug_exists(event_id: int, slug: str) -> bool: ...


class PersonalDataFieldValueRepositoryProtocol(Protocol):
    @staticmethod
    def save(entries: list[PersonalDataFieldValueData]) -> None: ...
    @staticmethod
    def read_for_facilitator_event(
        facilitator_id: int, event_id: int
    ) -> dict[str, str | list[str] | bool]: ...
    @staticmethod
    def list_values_for_facilitators(
        facilitator_ids: list[int], field_ids: list[int]
    ) -> dict[int, dict[str, str | list[str] | bool]]: ...
    @staticmethod
    def list_field_ids_for_facilitator_event(
        facilitator_id: int, event_id: int
    ) -> list[int]: ...
    @staticmethod
    def delete_by_facilitators(facilitator_ids: list[int]) -> None: ...
    @staticmethod
    def delete_for_facilitator_fields(
        facilitator_id: int, field_ids: list[int]
    ) -> int: ...


class ScheduleChangeAction(StrEnum):
    ASSIGN = auto()
    UNASSIGN = auto()
    REVERT = auto()


class ScheduleChangeLogData(TypedDict, total=False):
    event_id: int
    session_id: int
    user_id: int | None
    action: str
    old_space_id: int | None
    new_space_id: int | None
    old_start_time: datetime | None
    old_end_time: datetime | None
    new_start_time: datetime | None
    new_end_time: datetime | None


class ScheduleChangeLogDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pk: int
    event_id: int
    session_id: int
    session_title: str
    user_id: int | None
    user_name: str
    action: ScheduleChangeAction
    old_space_id: int | None
    old_space_name: str | None
    new_space_id: int | None
    new_space_name: str | None
    old_start_time: datetime | None
    old_end_time: datetime | None
    new_start_time: datetime | None
    new_end_time: datetime | None
    creation_time: datetime


class ScheduleChangeLogRepositoryProtocol(Protocol):
    @staticmethod
    def create(data: ScheduleChangeLogData) -> None: ...

    @staticmethod
    def read(pk: int) -> ScheduleChangeLogDTO: ...

    @staticmethod
    def list_by_event(
        event_pk: int, *, space_pk: int | None = None
    ) -> list[ScheduleChangeLogDTO]: ...

    @staticmethod
    def list_by_session(session_id: int) -> list[ScheduleChangeLogDTO]: ...

    @staticmethod
    def latest_pks_by_session(event_pk: int) -> dict[int, int]: ...

    @staticmethod
    def latest_pk_for_session(event_pk: int, session_id: int) -> int | None: ...


ContentFieldValue = str | int | bool | list[str] | None


class ContentFieldChange(TypedDict):
    # Identity only — no display text. `field` is the core-column key
    # (e.g. "title"); for dynamic session fields it is "" and `field_id`
    # holds the SessionField id. Labels are resolved per-request at render.
    field: str
    field_id: int | None
    old: ContentFieldValue
    new: ContentFieldValue


class ContentChangeLogData(TypedDict):
    event_id: int
    session_id: int
    user_id: int | None
    changes: list[ContentFieldChange]


@dataclass(frozen=True)
class SessionContentEditData:
    # The write payload for a single session content edit. `facilitator_ids`
    # None leaves the assignment untouched; a list (possibly empty) replaces it.
    # `field_values` None leaves dynamic answers untouched (partial POST guard).
    # `remove_field_ids` drops answers to fields the session's category no
    # longer asks for — the only edit the panel allows on those.
    # `resize_agenda_item` lets a duration change move the scheduled block's
    # end time. Only the organizer panel sets it; a facilitator's self-edit
    # writes the session row alone and leaves the timetable to the organizer.
    update: SessionUpdateData
    field_values: list[SessionFieldValueData] | None = None
    facilitator_ids: list[int] | None = None
    track_ids: list[int] | None = None
    time_slot_ids: list[int] | None = None
    remove_field_ids: list[int] | None = None
    resize_agenda_item: bool = False


class ContentChangeLogDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pk: int
    event_id: int
    session_id: int
    session_title: str
    user_id: int | None
    user_name: str
    changes: list[ContentFieldChange]
    creation_time: datetime

    @property
    def item_name(self) -> str:
        # What the shared change-log table shows for "which thing changed",
        # whichever kind of log it is rendering.
        return self.session_title


class ContentChangeLogRepositoryProtocol(Protocol):
    @staticmethod
    def create(data: ContentChangeLogData) -> None: ...

    @staticmethod
    def read(pk: int) -> ContentChangeLogDTO: ...

    @staticmethod
    def list_by_event(event_pk: int) -> list[ContentChangeLogDTO]: ...

    @staticmethod
    def latest_pks_by_session(event_pk: int) -> dict[int, int]: ...

    @staticmethod
    def latest_pk_for_session(event_pk: int, session_id: int) -> int | None: ...


class FacilitatorChangeLogData(TypedDict):
    event_id: int
    facilitator_id: int
    user_id: int | None
    changes: list[ContentFieldChange]


class FacilitatorChangeLogDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pk: int
    event_id: int
    facilitator_id: int
    facilitator_name: str
    user_id: int | None
    user_name: str
    changes: list[ContentFieldChange]
    creation_time: datetime

    @property
    def item_name(self) -> str:
        # See ContentChangeLogDTO.item_name.
        return self.facilitator_name


class FacilitatorChangeLogRepositoryProtocol(Protocol):
    @staticmethod
    def create(data: FacilitatorChangeLogData) -> None: ...

    @staticmethod
    def list_by_event(event_pk: int) -> list[FacilitatorChangeLogDTO]: ...


class UnitOfWorkProtocol(Protocol):
    @staticmethod
    def atomic() -> AbstractContextManager[None]: ...
    @staticmethod
    def savepoint() -> AbstractContextManager[None]: ...
    @property
    def active_users(self) -> UserRepositoryProtocol: ...
    @property
    def agenda_items(self) -> AgendaItemRepositoryProtocol: ...
    @property
    def anonymous_users(self) -> UserRepositoryProtocol: ...
    @property
    def companions(self) -> CompanionRepositoryProtocol: ...
    @property
    def event_proposal_settings(self) -> EventProposalSettingsRepositoryProtocol: ...
    @property
    def events(self) -> EventRepositoryProtocol: ...
    @property
    def event_settings(self) -> EventSettingsRepositoryProtocol: ...
    @property
    def facilitators(self) -> FacilitatorRepositoryProtocol: ...
    @property
    def personal_data_fields(self) -> PersonalDataFieldRepositoryProtocol: ...
    @property
    def proposal_categories(self) -> ProposalCategoryRepositoryProtocol: ...
    @property
    def session_fields(self) -> SessionFieldRepositoryProtocol: ...
    @property
    def sessions(self) -> SessionRepositoryProtocol: ...
    @property
    def spheres(self) -> SphereRepositoryProtocol: ...
    @property
    def spaces(self) -> SpaceRepositoryProtocol: ...
    @property
    def time_slots(self) -> TimeSlotRepositoryProtocol: ...
    @property
    def tracks(self) -> TrackRepositoryProtocol: ...
    @property
    def encounters(self) -> EncounterRepositoryProtocol: ...
    @property
    def encounter_rsvps(self) -> EncounterRSVPRepositoryProtocol: ...
    @property
    def enrollment_configs(self) -> EnrollmentConfigRepositoryProtocol: ...
    @property
    def personal_data_field_values(
        self,
    ) -> PersonalDataFieldValueRepositoryProtocol: ...
    @property
    def schedule_change_logs(self) -> ScheduleChangeLogRepositoryProtocol: ...


class TicketAPIProtocol(Protocol):
    def fetch_membership_count(self, user_email: str) -> int: ...


DEFAULT_FIELD_MAX_LENGTH = 50


class CacheProtocol(Protocol):
    @staticmethod
    def get(key: str) -> object: ...
    @staticmethod
    def set(key: str, value: object, timeout: int | None = None) -> None: ...


class DependencyInjectorProtocol(Protocol):
    @property
    def uow(self) -> UnitOfWorkProtocol: ...
    @property
    def ticket_api(self) -> TicketAPIProtocol: ...
    @property
    def cache(self) -> CacheProtocol: ...
    @staticmethod
    def gravatar_url(email: str) -> str | None: ...


class RootRequestProtocol(Protocol):
    path: str
    di: DependencyInjectorProtocol
    services: ServicesProtocol
    context: RequestContext


@dataclass
class VirtualEnrollmentConfig:
    allowed_slots: int = 0
    has_domain_config: bool = False
    has_user_config: bool = False


class MembershipAPIError(Exception):
    pass


class UserEnrollmentConfigData(TypedDict):
    allowed_slots: int
    enrollment_config_id: int
    fetched_from_api: bool
    last_check: datetime | None
    user_email: str
