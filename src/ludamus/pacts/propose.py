"""Contracts for proposing a session: the wizard's ports and its service face."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple, Protocol, TypedDict

from pydantic import BaseModel

from ludamus.pacts.fields import FieldValue

if TYPE_CHECKING:
    from ludamus.pacts.crowd import UserRepositoryProtocol
    from ludamus.pacts.event import (
        EventDTO,
        EventProposalSettingsDTO,
        EventProposalSettingsRepositoryProtocol,
        EventRepositoryProtocol,
    )
    from ludamus.pacts.facilitators import FacilitatorRepositoryProtocol
    from ludamus.pacts.fields import (
        OrganizerFieldDTO,
        PersonalDataFieldRepositoryProtocol,
        PersonalDataFieldValueRepositoryProtocol,
        SessionFieldRepositoryProtocol,
    )
    from ludamus.pacts.images import UploadedFileProtocol
    from ludamus.pacts.proposal_categories import (
        ProposalCategoryDTO,
        ProposalCategoryRepositoryProtocol,
        SessionFieldRequirementDTO,
        TimeSlotRequirementDTO,
    )
    from ludamus.pacts.sessions import SessionRepositoryProtocol
    from ludamus.pacts.tracks import TrackDTO, TrackRepositoryProtocol


# NOTE: the wizard stores the presenter name under this key; the gate writes
# it, the mill reads it.
FACILITATOR_NAME_FIELD = "facilitator_name"


class AccountAnswersDTO(BaseModel):
    """What the proposer's account already answers on the personal step."""

    email: str = ""
    # Wizard keys (`personal_<slug>`) to answers.
    personal_data: dict[str, str] = {}


# NOTE: session fields belong to an event, so the slug is the only key that
# can carry an answer over to another event's form.
type AnswersBySlug = dict[str, FieldValue]


class EarlierSessionDTO(BaseModel):
    """One of the proposer's own sessions from an earlier event."""

    pk: int
    title: str
    event_name: str
    description: str
    participants_limit: int
    min_age: int
    duration: str


class ReusableSessionRecord(BaseModel):
    """An earlier session as stored, before deciding which answers carry over."""

    session: EarlierSessionDTO
    public_answers: AnswersBySlug
    private_answers: AnswersBySlug
    presented: bool


class ReusableSessionDTO(BaseModel):
    """An earlier session to start from, with the answers that carry over."""

    session: EarlierSessionDTO
    field_values: AnswersBySlug


class ReusableSessionRepositoryProtocol(Protocol):
    @staticmethod
    def list_reusable(
        *, user_id: int, sphere_id: int, exclude_event_id: int, limit: int
    ) -> list[ReusableSessionRecord]: ...


class ProposeRepos(NamedTuple):
    """The repos the propose wizard reads its steps and writes a proposal through."""

    events: EventRepositoryProtocol
    event_proposal_settings: EventProposalSettingsRepositoryProtocol
    categories: ProposalCategoryRepositoryProtocol
    tracks: TrackRepositoryProtocol
    sessions: SessionRepositoryProtocol
    reusable_sessions: ReusableSessionRepositoryProtocol
    session_fields: SessionFieldRepositoryProtocol
    personal_fields: PersonalDataFieldRepositoryProtocol
    personal_data_field_values: PersonalDataFieldValueRepositoryProtocol
    facilitators: FacilitatorRepositoryProtocol
    users: UserRepositoryProtocol


class ProposeSessionServiceProtocol(Protocol):
    def get_event(self, slug: str, sphere_id: int) -> EventDTO: ...
    def get_proposal_settings(self, event_id: int) -> EventProposalSettingsDTO: ...
    def get_or_create_proposal_settings(
        self, event_id: int
    ) -> EventProposalSettingsDTO: ...
    def get_categories(self, event_id: int) -> list[ProposalCategoryDTO]: ...
    def get_category(self, pk: int, event_id: int) -> ProposalCategoryDTO: ...
    def get_personal_fields(self, event_id: int) -> list[OrganizerFieldDTO]: ...
    def get_session_requirements(
        self, category_id: int
    ) -> list[SessionFieldRequirementDTO]: ...
    def get_timeslot_requirements(
        self, category_id: int
    ) -> list[TimeSlotRequirementDTO]: ...
    def get_public_tracks(self, event_id: int) -> list[TrackDTO]: ...
    def get_saved_personal_data(
        self, *, event_id: int, user_id: int | None
    ) -> dict[str, str | list[str] | bool]: ...
    def get_account_answers(
        self, *, user_id: int | None, fields: list[OrganizerFieldDTO]
    ) -> AccountAnswersDTO: ...
    def check_rate_limit(self, *, ip: str, event_id: int) -> bool: ...
    def list_reusable_sessions(
        self, *, user_id: int | None, event: EventDTO
    ) -> list[ReusableSessionDTO]: ...
    def submit(
        self,
        event: EventDTO,
        wizard_data: WizardData,
        *,
        cover_image: UploadedFileProtocol | None = None,
        user_id: int | None = None,
        user_slug: str | None = None,
        language: str,
    ) -> ProposeSessionResult: ...


class WizardData(TypedDict, total=False):
    category_id: int
    contact_email: str
    personal_data: dict[str, str]
    session_data: dict[str, FieldValue | int]
    time_slot_ids: list[int]
    track_pks: list[int]


@dataclass
class ProposeSessionResult:
    session_id: int
    title: str
