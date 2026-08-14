"""Organizer panel DTOs and protocols for the proposals and facilitators lists."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from ludamus.pacts.crowd import UserDTO, UserRepositoryProtocol
    from ludamus.pacts.event import FacilitatorListItemDTO
    from ludamus.pacts.fields import OrganizerFieldDTO
    from ludamus.pacts.guild import GuildRepositoryProtocol
    from ludamus.pacts.legacy import (
        FacilitatorChangeLogDTO,
        FacilitatorChangeLogRepositoryProtocol,
        FacilitatorDTO,
        FacilitatorRepositoryProtocol,
        PersonalDataFieldRepositoryProtocol,
        PersonalDataFieldValueRepositoryProtocol,
        ProposalCategoryDTO,
        ProposalCategoryRepositoryProtocol,
        SessionData,
        SessionDTO,
        SessionFieldRepositoryProtocol,
        SessionListItemDTO,
        SessionRepositoryProtocol,
    )


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

STATUS_ALL = "all"


@dataclass
class ProposalListQuery:
    """The proposals list's requested view: filters as the request spelled them.

    `raw_field_filters` is keyed by session-field pk with the value untouched
    from the query string; the service resolves it against the event's own
    fields. `category`, `status`, and `sort` are raw request values too.
    """

    search: str = ""
    category: str = ""
    status: str = ""
    track_pk: int | None = None
    multi_tracks: bool = False
    sort: str = ""
    raw_field_filters: dict[int, str] = field(default_factory=dict)


@dataclass
class ProposalDraft:
    """A new proposal as the create form spelled it.

    `base_slug` is the slugified title — the service uniquifies it.
    `field_values` holds parsed session-field answers keyed by field pk; the
    service attaches the session id once the row exists.
    """

    data: SessionData
    base_slug: str
    facilitator_ids: list[int] = field(default_factory=list)
    field_values: dict[int, str | list[str] | bool] = field(default_factory=dict)
    track_ids: list[int] = field(default_factory=list)
    time_slot_ids: list[int] = field(default_factory=list)


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


@dataclass
class ProposalPanelRepos:
    """The repos the panel's proposals list reads and writes through."""

    sessions: SessionRepositoryProtocol
    session_fields: SessionFieldRepositoryProtocol
    proposal_categories: ProposalCategoryRepositoryProtocol
    panel_settings: EventPanelSettingsRepositoryProtocol


@dataclass
class FacilitatorPanelRepos:  # pylint: disable=too-many-instance-attributes
    """The repos the panel's facilitator list reads and writes through."""

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
    flagged: bool = False
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

    `values` holds parsed personal-data answers keyed by field pk;
    `base_slug` is the slugified display name — the service uniquifies it.
    """

    display_name: str
    base_slug: str
    accreditation_type: str
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


@dataclass
class FacilitatorMergeContextDTO:
    """Read aggregate for the merge reconcile screen.

    `values` maps facilitator pk -> field slug -> that facilitator's answer,
    so the screen can offer a per-attribute choice where sources disagree.
    """

    facilitators: list[FacilitatorDTO]
    fields: list[OrganizerFieldDTO]
    values: dict[int, dict[str, str | list[str] | bool]]


class FacilitatorPanelServiceProtocol(PanelColumnServiceProtocol, Protocol):
    def list_context(
        self, *, event_id: int, query: FacilitatorListQuery
    ) -> FacilitatorListContextDTO: ...
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
        self, *, event_id: int, facilitator_slug: str
    ) -> FacilitatorDetailContextDTO: ...
    def create_facilitator(
        self, *, event_id: int, data: FacilitatorCreateData, user_id: int | None = None
    ) -> FacilitatorDTO: ...
    def facilitator_history(
        self, *, event_id: int, facilitator_slug: str
    ) -> tuple[str, list[FacilitatorChangeLogDTO]]: ...
    def merge_context(
        self, *, event_id: int, facilitator_slugs: list[str]
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
    def assign_guild(
        self, *, event_id: int, sphere_id: int, facilitator_slug: str, guild_pk: int
    ) -> bool: ...
    def set_flag(
        self, *, event_id: int, facilitator_slug: str, flagged: bool
    ) -> None: ...
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
