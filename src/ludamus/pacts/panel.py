"""Organizer panel DTOs and protocols for the proposals and facilitators lists."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from ludamus.pacts.crowd import UserDTO, UserRepositoryProtocol
    from ludamus.pacts.legacy import (
        FacilitatorChangeLogDTO,
        FacilitatorChangeLogRepositoryProtocol,
        FacilitatorDTO,
        FacilitatorListItemDTO,
        FacilitatorRepositoryProtocol,
        PersonalDataFieldDTO,
        PersonalDataFieldRepositoryProtocol,
        PersonalDataFieldValueRepositoryProtocol,
        ProposalCategoryDTO,
        SessionData,
        SessionFieldDTO,
        SessionListItemDTO,
        SessionRepositoryProtocol,
    )


class EmptyColumnSelectionError(Exception):
    """A columns chooser submitted nothing this event recognises as a column."""


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
class ProposalListContextDTO:
    """Read aggregate for the panel's proposals list.

    `category_pk`, `status`, and `sort` echo back the query values that
    survived validation, so the view renders exactly what was filtered on.
    """

    proposals: list[SessionListItemDTO]
    filterable_fields: list[SessionFieldDTO]
    categories: list[ProposalCategoryDTO]
    category_pk: int | None
    status: str | None
    sort: str
    columns: list[PanelColumnDTO]


class ProposalPanelServiceProtocol(Protocol):
    def list_context(
        self, *, event_id: int, query: ProposalListQuery
    ) -> ProposalListContextDTO: ...
    def list_deleted(self, event_id: int) -> list[SessionListItemDTO]: ...
    def column_values(
        self, *, session_ids: list[int], field_ids: list[int]
    ) -> dict[int, dict[str, str | list[str] | bool]]: ...
    def columns_context(self, event_id: int) -> PanelColumnsContextDTO: ...
    def set_columns(self, *, event_id: int, columns: list[str]) -> None: ...
    def create_proposal(
        self,
        *,
        event_id: int,
        data: SessionData,
        base_slug: str,
        facilitator_ids: list[int],
    ) -> int: ...


@dataclass
class FacilitatorPanelRepos:
    """The repos the panel's facilitator list reads and writes through."""

    facilitators: FacilitatorRepositoryProtocol
    personal_data_fields: PersonalDataFieldRepositoryProtocol
    personal_data_field_values: PersonalDataFieldValueRepositoryProtocol
    facilitator_change_logs: FacilitatorChangeLogRepositoryProtocol
    panel_settings: EventPanelSettingsRepositoryProtocol
    sessions: SessionRepositoryProtocol
    users: UserRepositoryProtocol


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
    sort: str = ""
    raw_field_filters: dict[int, str] = field(default_factory=dict)


@dataclass
class FacilitatorListContextDTO:
    """Read aggregate for the panel's facilitator list."""

    facilitators: list[FacilitatorListItemDTO]
    filterable_fields: list[PersonalDataFieldDTO]
    field_filters: dict[int, str | bool]
    columns: list[PanelColumnDTO]


@dataclass
class FacilitatorCreateData:
    """A new facilitator as the create form spelled it.

    `values` holds parsed personal-data answers keyed by field pk;
    `base_slug` is the slugified display name — the service uniquifies it.
    """

    display_name: str
    base_slug: str
    accreditation_type: str
    values: dict[int, str | list[str] | bool] = field(default_factory=dict)


@dataclass
class FacilitatorDetailContextDTO:
    """Read aggregate for one facilitator's detail page."""

    facilitator: FacilitatorDTO
    personal_data_items: list[
        tuple[PersonalDataFieldDTO, str | list[str] | bool | None]
    ]
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
    fields: list[PersonalDataFieldDTO]
    values: dict[int, dict[str, str | list[str] | bool]]


class FacilitatorPanelServiceProtocol(Protocol):
    def list_context(
        self, *, event_id: int, query: FacilitatorListQuery
    ) -> FacilitatorListContextDTO: ...
    def list_fields(self, event_id: int) -> list[PersonalDataFieldDTO]: ...
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
        target_slug: str,
        facilitator_slugs: list[str],
        data: FacilitatorMergeData,
    ) -> None: ...
    def column_values(
        self, *, facilitator_ids: list[int], field_ids: list[int]
    ) -> dict[int, dict[str, str | list[str] | bool]]: ...
    def columns_context(self, event_id: int) -> PanelColumnsContextDTO: ...
    def set_columns(self, *, event_id: int, columns: list[str]) -> None: ...
    def set_flag(
        self, *, event_id: int, facilitator_slug: str, flagged: bool
    ) -> None: ...
    def set_accreditation(
        self,
        *,
        event_id: int,
        facilitator_slug: str,
        accreditation_type: str,
        user_id: int | None = None,
    ) -> None: ...
