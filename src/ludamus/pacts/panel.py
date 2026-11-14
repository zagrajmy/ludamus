"""Organizer panel DTOs and protocols for the proposals and facilitators lists."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from ludamus.pacts.availability import AvailabilityDTO
    from ludamus.pacts.event import EventRepositoryProtocol, FacilitatorListItemDTO
    from ludamus.pacts.facilitators import (
        FacilitatorChangeLogDTO,
        FacilitatorChangeLogRepositoryProtocol,
        FacilitatorDTO,
        FacilitatorRepositoryProtocol,
    )
    from ludamus.pacts.fields import (
        OrganizerFieldDTO,
        PersonalDataFieldRepositoryProtocol,
        PersonalDataFieldValueData,
        PersonalDataFieldValueRepositoryProtocol,
        SessionFieldRepositoryProtocol,
        SessionFieldValueDTO,
    )
    from ludamus.pacts.guild import GuildRepositoryProtocol
    from ludamus.pacts.proposal_categories import (
        ProposalCategoryDTO,
        ProposalCategoryRepositoryProtocol,
        SessionFieldRequirementDTO,
    )
    from ludamus.pacts.sessions import (
        SessionContentEditData,
        SessionData,
        SessionDTO,
        SessionListItemDTO,
        SessionRepositoryProtocol,
    )
    from ludamus.pacts.timetable import (
        AgendaItemDTO,
        AgendaItemRepositoryProtocol,
        ScheduleChangeLogDTO,
        ScheduleChangeLogRepositoryProtocol,
    )
    from ludamus.pacts.tracks import TrackDTO, TrackRepositoryProtocol
    from ludamus.pacts.user import UserDTO, UserRepositoryProtocol


class SourceRowIdMissingError(Exception):
    pass


class EmptyColumnSelectionError(Exception):
    """A columns chooser submitted nothing this event recognises as a column."""


class MergeErrorReason(StrEnum):
    """Why a facilitator merge was refused — each maps to its own user copy."""

    TOO_FEW = "too_few"
    NO_TARGET = "no_target"
    NO_DISPLAY_NAME = "no_display_name"
    BAD_ACCREDITATION = "bad_accreditation"
    MULTIPLE_LINKED = "multiple_linked"


class FacilitatorMergeError(Exception):
    """Raised when a facilitator merge violates a domain invariant."""

    def __init__(self, reason: MergeErrorReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


class PanelFieldProtocol(Protocol):
    """A dynamic field usable as a list column (session or personal-data)."""

    pk: int
    name: str
    slug: str
    order: int


FIELD_KEY_PREFIX = "field_"

# Which built-in columns each list offers, in their default order. The gates
# layer decides what they are called and how their cells render.
FACILITATOR_BUILTIN_KEYS = (
    "name",
    "linked",
    "guild",
    "sessions",
    "accreditation",
    "organizer",
)
PROPOSAL_BUILTIN_KEYS = ("title", "host", "category", "status", "created")


@dataclass
class PanelColumnDTO:
    """One list column: a built-in key or a dynamic field ("field_<pk>")."""

    key: str
    field: PanelFieldProtocol | None = None


@dataclass
class PanelColumnsContextDTO:
    """Read aggregate for a columns chooser page."""

    chosen: list[PanelColumnDTO]
    available: list[PanelColumnDTO]


class EventPanelSettingsDTO(BaseModel):
    """Organizer-only backoffice settings for an event."""

    model_config = ConfigDict(from_attributes=True)

    facilitator_columns: list[str] = []
    proposal_columns: list[str] = []
    pk: int


class EventPanelSettingsRepositoryProtocol(Protocol):
    @staticmethod
    def read_or_create(event_id: int) -> EventPanelSettingsDTO: ...
    @staticmethod
    def update_facilitator_columns(event_id: int, columns: list[str]) -> None: ...
    @staticmethod
    def update_proposal_columns(event_id: int, columns: list[str]) -> None: ...


SCHEDULED_FILTER = "scheduled"

# Explicit "no status filter" value. An absent param means the pending backlog,
# so "show everything" has to travel in the query — forms, the Clear link and
# post-action redirects all echo it back.
STATUS_ALL = "all"


@dataclass
class ProposalListQuery:
    """The proposals list's requested view: filters as the request spelled them.

    `raw_field_filters` is keyed by session-field pk with the value untouched
    from the query string; the service resolves it against the event's own
    fields. `category_pk`, `status`, and `sort` are request values too.
    """

    search: str = ""
    category_pk: int | None = None
    status: str = ""
    track_pk: int | None = None
    multi_tracks: bool = False
    sort: str = ""
    raw_field_filters: dict[int, str] = field(default_factory=dict)


@dataclass
class ProposalDraft:
    """A new proposal as the create form spelled it.

    The service slugs and uniquifies `data["title"]`.
    `field_values` holds parsed session-field answers keyed by field pk; the
    service attaches the session id once the row exists.
    """

    data: SessionData
    facilitator_ids: list[int] = field(default_factory=list)
    field_values: dict[int, str | list[str] | bool] = field(default_factory=dict)
    track_ids: list[int] = field(default_factory=list)
    availability: list[AvailabilityDTO] = field(default_factory=list)


@dataclass
class ProposalListContextDTO:
    """Read aggregate for the panel's proposals list.

    `category_pk`, `status`, and `sort` echo back the query values that
    survived validation, so the view renders exactly what was filtered on.
    """

    proposals: list[SessionListItemDTO]
    filterable_fields: list[OrganizerFieldDTO]
    categories: list[ProposalCategoryDTO]
    category_pk: int | None
    status: str | None
    sort: str
    columns: list[PanelColumnDTO]


class PanelColumnServiceProtocol(Protocol):
    """What the columns chooser needs of a list's service, either list."""

    def columns_context(self, event_id: int) -> PanelColumnsContextDTO: ...
    def set_columns(self, *, event_id: int, columns: list[str]) -> None: ...


class ProposalPanelServiceProtocol(PanelColumnServiceProtocol, Protocol):
    def list_context(
        self, *, event_id: int, query: ProposalListQuery
    ) -> ProposalListContextDTO: ...
    def list_deleted(self, event_id: int) -> list[SessionListItemDTO]: ...
    def read_proposal(self, *, event_id: int, proposal_id: int) -> SessionDTO: ...
    def column_values(
        self, *, session_ids: list[int], field_ids: list[int]
    ) -> dict[int, dict[str, str | list[str] | bool]]: ...
    def create_proposal(self, *, event_id: int, draft: ProposalDraft) -> int: ...
    def create_accepted_session(
        self, *, event_id: int, source_row_id: str, draft: ProposalDraft
    ) -> int: ...
    def set_session_facilitator_name(
        self, *, event_id: int, session_id: int, facilitator_name: str
    ) -> None: ...


@dataclass
class ProposalPanelRepos:
    """The repos the panel's proposals list reads and writes through."""

    sessions: SessionRepositoryProtocol
    session_fields: SessionFieldRepositoryProtocol
    proposal_categories: ProposalCategoryRepositoryProtocol
    panel_settings: EventPanelSettingsRepositoryProtocol
    facilitators: FacilitatorRepositoryProtocol
    tracks: TrackRepositoryProtocol


@dataclass
class ProposalRecordRepos:
    """What one proposal's page reads beside the event's own catalogue."""

    agenda_items: AgendaItemRepositoryProtocol
    schedule_change_logs: ScheduleChangeLogRepositoryProtocol
    personal_data_fields: PersonalDataFieldRepositoryProtocol
    personal_data_field_values: PersonalDataFieldValueRepositoryProtocol


@dataclass
class ProposalScheduleDTO:
    """Where a proposal stands on the timetable, and how it got there."""

    agenda_item: AgendaItemDTO | None
    logs: list[ScheduleChangeLogDTO]
    availability: list[AvailabilityDTO]


@dataclass
class ProposalDetailDTO:
    """Read aggregate for one proposal's panel page."""

    proposal: SessionDTO
    category_name: str | None
    tracks: list[TrackDTO]
    field_values: list[SessionFieldValueDTO]
    facilitators: list[FacilitatorDTO]
    presenter: UserDTO | None
    schedule: ProposalScheduleDTO


@dataclass
class ProposalFormFieldsDTO:
    """The proposal form's category-dependent part.

    `category` is the one the form renders fields for: the requested one if
    the event has it, else the proposal's own, else the event's first.
    `session_fields` names the answers the category no longer asks for, so it
    is only read for an existing proposal.
    """

    proposal: SessionDTO | None
    categories: list[ProposalCategoryDTO]
    category: ProposalCategoryDTO | None
    requirements: list[SessionFieldRequirementDTO]
    field_values: list[SessionFieldValueDTO]
    session_fields: list[OrganizerFieldDTO]


@dataclass
class ProposalAssignmentsDTO:
    """What a proposal is assigned to now; empty for one not yet created."""

    facilitators: list[FacilitatorDTO] = field(default_factory=list)
    track_ids: list[int] = field(default_factory=list)
    availability: list[AvailabilityDTO] = field(default_factory=list)


@dataclass
class ProposalFormDTO:
    """Read aggregate for the proposal create/edit page.

    The pickers offer the event's facilitators and tracks; the parts of days
    on offer come from the event's own hours.
    Personal data belongs to an existing proposal's facilitators, so a create
    page reads none.
    """

    fields: ProposalFormFieldsDTO
    facilitators: list[FacilitatorListItemDTO]
    tracks: list[TrackDTO]
    assigned: ProposalAssignmentsDTO
    personal_data_fields: list[OrganizerFieldDTO]
    personal_data_values: dict[int, dict[str, str | list[str] | bool]]


@dataclass
class ProposalEdit:
    """An organizer's save of the proposal form: content, then personal data."""

    content: SessionContentEditData
    personal_data: dict[int, list[PersonalDataFieldValueData]] = field(
        default_factory=dict
    )


class ProposalPageServiceProtocol(Protocol):
    def detail(self, *, event_id: int, proposal_id: int) -> ProposalDetailDTO: ...
    def form_fields(
        self, *, event_id: int, proposal_id: int | None, category_id: int | None
    ) -> ProposalFormFieldsDTO: ...
    def form(
        self, *, event_id: int, proposal_id: int | None, category_id: int | None
    ) -> ProposalFormDTO: ...
    def update(
        self, *, event_id: int, proposal_id: int, user_id: int, edit: ProposalEdit
    ) -> None: ...
    def set_facilitators(
        self, *, event_id: int, proposal_id: int, facilitator_ids: list[int]
    ) -> None: ...


@dataclass
class FacilitatorPanelRepos:  # pylint: disable=too-many-instance-attributes
    """The repos the panel's facilitator list reads and writes through."""

    events: EventRepositoryProtocol
    facilitators: FacilitatorRepositoryProtocol
    personal_data_fields: PersonalDataFieldRepositoryProtocol
    personal_data_field_values: PersonalDataFieldValueRepositoryProtocol
    facilitator_change_logs: FacilitatorChangeLogRepositoryProtocol
    panel_settings: EventPanelSettingsRepositoryProtocol
    sessions: SessionRepositoryProtocol
    users: UserRepositoryProtocol
    guilds: GuildRepositoryProtocol


@dataclass
class FacilitatorListQuery:
    """The list's requested view: filters as the request spelled them.

    `raw_field_filters` is keyed by personal-data field pk with the value
    untouched from the query string; the service resolves it against the
    event's own fields.
    """

    search: str = ""
    accreditation: str = ""
    # "", "mine" or "unassigned" — one choice, so "filter by me" and "filter by
    # nobody" can never both be asked for. `current_user_id` is who "mine"
    # means, not a filter of its own.
    organizer: str = ""
    current_user_id: int | None = None
    sort: str = ""
    raw_field_filters: dict[int, str] = field(default_factory=dict)


@dataclass
class FacilitatorListContextDTO:
    """Read aggregate for the panel's facilitator list."""

    facilitators: list[FacilitatorListItemDTO]
    filterable_fields: list[OrganizerFieldDTO]
    field_filters: dict[int, str | bool]
    columns: list[PanelColumnDTO]


@dataclass
class FacilitatorFilterOptionsDTO:
    facilitators: list[FacilitatorListItemDTO]
    columns: list[PanelColumnDTO]
    has_more: bool


@dataclass
class FacilitatorCreateData:
    """A new facilitator as the create form spelled it.

    `values` holds parsed personal-data answers keyed by field pk. The service
    slugs `display_name` itself.
    """

    display_name: str
    accreditation_type: str
    is_collective: bool = False
    organizer_id: int | None = None
    values: dict[int, str | list[str] | bool] = field(default_factory=dict)


@dataclass
class FacilitatorDetailContextDTO:
    """Read aggregate for one facilitator's detail page."""

    facilitator: FacilitatorDTO
    personal_data_items: list[tuple[OrganizerFieldDTO, str | list[str] | bool | None]]
    linked_user: UserDTO | None
    sessions: list[SessionListItemDTO]


@dataclass
class FacilitatorMergeData:
    """Reconciled values the merge target keeps.

    `keep_values_from` maps field pk to the pk of the facilitator whose answer
    the target keeps; the service resolves the answer inside the merge
    transaction and drops keys naming a foreign field or facilitator.
    """

    display_name: str
    accreditation_type: str
    keep_values_from: dict[int, int] = field(default_factory=dict)


MIN_MERGE_FACILITATORS = 2


@dataclass
class FacilitatorMergeContextDTO:
    """Read aggregate for the merge reconcile screen.

    Each choice list offers a control only where the sources disagree, with the
    target's own answer checked; an empty list means every source agrees, and
    the matching `unanimous_*` value is what the merge keeps.
    `accreditation_choices` holds (value, source names, checked);
    `field_conflicts` holds per field (holder pk, answer, source names, checked).
    """

    facilitators: list[FacilitatorDTO]
    target: FacilitatorDTO
    name_choices: list[tuple[str, bool]]
    unanimous_display_name: str | None
    accreditation_choices: list[tuple[str, str, bool]]
    unanimous_accreditation: str | None
    field_conflicts: list[
        tuple[OrganizerFieldDTO, list[tuple[int, str | list[str] | bool, str, bool]]]
    ]


class FacilitatorPanelServiceProtocol(PanelColumnServiceProtocol, Protocol):
    def list_context(
        self, *, event_id: int, query: FacilitatorListQuery
    ) -> FacilitatorListContextDTO: ...
    def list_deleted(self, event_id: int) -> list[FacilitatorListItemDTO]: ...
    def filter_options(
        self, *, event_id: int, search: str, pinned: set[int], limit: int
    ) -> FacilitatorFilterOptionsDTO: ...
    def merge_basket(
        self, *, event_id: int, slugs: list[str]
    ) -> list[FacilitatorListItemDTO]: ...
    def search_candidates(
        self, *, event_id: int, search: str
    ) -> list[FacilitatorListItemDTO]: ...
    def list_fields(self, event_id: int) -> list[OrganizerFieldDTO]: ...
    def detail_context(
        self, *, event_id: int, facilitator_slug: str, include_deleted: bool
    ) -> FacilitatorDetailContextDTO: ...
    def create_facilitator(
        self, *, event_id: int, data: FacilitatorCreateData, user_id: int | None = None
    ) -> FacilitatorDTO: ...
    def find_or_create_facilitator(
        self, *, event_id: int, data: FacilitatorCreateData, user_id: int | None = None
    ) -> FacilitatorDTO: ...
    def facilitator_history(
        self, *, event_id: int, facilitator_slug: str
    ) -> tuple[str, list[FacilitatorChangeLogDTO]]: ...
    def merge_context(
        self, *, event_id: int, facilitator_slugs: list[str], target_slug: str
    ) -> FacilitatorMergeContextDTO: ...
    def merge(
        self,
        *,
        event_id: int,
        sphere_id: int,
        target_slug: str,
        facilitator_slugs: list[str],
        data: FacilitatorMergeData,
        user_id: int | None = None,
    ) -> None: ...
    def column_values(
        self, *, facilitator_ids: list[int], field_ids: list[int]
    ) -> dict[int, dict[str, str | list[str] | bool]]: ...
    def delete(
        self, *, event_id: int, facilitator_slug: str, user_id: int | None = None
    ) -> None: ...
    def restore(
        self, *, event_id: int, facilitator_slug: str, user_id: int | None = None
    ) -> None: ...
    def assign_guild(
        self, *, event_id: int, sphere_id: int, facilitator_slug: str, guild_pk: int
    ) -> bool: ...
    def assign_organizer(
        self, *, event_id: int, facilitator_slug: str, organizer_id: int
    ) -> None: ...
    def unassign_organizer(
        self, *, event_id: int, facilitator_slug: str, organizer_id: int, force: bool
    ) -> None: ...
    def set_accreditation(
        self,
        *,
        event_id: int,
        facilitator_slug: str,
        accreditation_type: str,
        user_id: int | None = None,
    ) -> None: ...
