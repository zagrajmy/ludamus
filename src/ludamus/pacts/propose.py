"""Contracts for proposing a session: the wizard's ports and its service face."""

from typing import TYPE_CHECKING, NamedTuple, Protocol

if TYPE_CHECKING:
    from ludamus.pacts.crowd import UserRepositoryProtocol
    from ludamus.pacts.legacy import (
        EventDTO,
        EventProposalSettingsDTO,
        EventProposalSettingsRepositoryProtocol,
        EventRepositoryProtocol,
        FacilitatorRepositoryProtocol,
        PersonalDataFieldRepositoryProtocol,
        PersonalDataFieldValueRepositoryProtocol,
        PersonalFieldRequirementDTO,
        ProposalCategoryDTO,
        ProposalCategoryRepositoryProtocol,
        ProposeSessionResult,
        SessionFieldRepositoryProtocol,
        SessionFieldRequirementDTO,
        SessionRepositoryProtocol,
        TimeSlotRequirementDTO,
        TrackDTO,
        TrackRepositoryProtocol,
        UploadedFileProtocol,
        WizardData,
    )


class ProposeRepos(NamedTuple):
    """The repos the propose wizard reads its steps and writes a proposal through."""

    events: EventRepositoryProtocol
    event_proposal_settings: EventProposalSettingsRepositoryProtocol
    categories: ProposalCategoryRepositoryProtocol
    tracks: TrackRepositoryProtocol
    sessions: SessionRepositoryProtocol
    session_fields: SessionFieldRepositoryProtocol
    personal_fields: PersonalDataFieldRepositoryProtocol
    personal_data_field_values: PersonalDataFieldValueRepositoryProtocol
    facilitators: FacilitatorRepositoryProtocol
    users: UserRepositoryProtocol


class ProposeSessionServiceProtocol(Protocol):
    def get_event(self, slug: str, sphere_id: int) -> EventDTO: ...
    @staticmethod
    def is_proposal_active(event: EventDTO) -> bool: ...
    def get_proposal_settings(self, event_id: int) -> EventProposalSettingsDTO: ...
    def get_or_create_proposal_settings(
        self, event_id: int
    ) -> EventProposalSettingsDTO: ...
    def get_categories(self, event_id: int) -> list[ProposalCategoryDTO]: ...
    def get_category(self, pk: int, event_id: int) -> ProposalCategoryDTO: ...
    def get_personal_requirements(
        self, category_id: int
    ) -> list[PersonalFieldRequirementDTO]: ...
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
    def check_rate_limit(self, *, ip: str, event_id: int) -> bool: ...
    def submit(
        self,
        event: EventDTO,
        wizard_data: WizardData,
        *,
        cover_image: UploadedFileProtocol | None = None,
        user_id: int | None = None,
        user_slug: str | None = None,
    ) -> ProposeSessionResult: ...
