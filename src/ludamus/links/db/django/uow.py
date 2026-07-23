from functools import cached_property
from typing import TYPE_CHECKING

from django.db import transaction

from ludamus.links.db.django import crowd, repositories
from ludamus.links.db.django.agenda_item import AgendaItemRepository
from ludamus.links.db.django.schedule_change_log import ScheduleChangeLogRepository
from ludamus.pacts import UnitOfWorkProtocol
from ludamus.pacts.crowd import UserType

if TYPE_CHECKING:
    from contextlib import AbstractContextManager


class UnitOfWork(UnitOfWorkProtocol):  # ruff:ignore[too-many-public-methods]
    @staticmethod
    def atomic() -> AbstractContextManager[None]:
        return transaction.atomic()

    @cached_property
    def active_users(self) -> crowd.UserRepository:
        return crowd.UserRepository(user_type=UserType.ACTIVE)

    @cached_property
    def agenda_items(self) -> AgendaItemRepository:
        return AgendaItemRepository()

    @cached_property
    def anonymous_users(self) -> crowd.UserRepository:
        return crowd.UserRepository(user_type=UserType.ANONYMOUS)

    @cached_property
    def companions(self) -> crowd.CompanionRepository:
        return crowd.CompanionRepository()

    @cached_property
    def event_proposal_settings(self) -> repositories.EventProposalSettingsRepository:
        return repositories.EventProposalSettingsRepository()

    @cached_property
    def event_settings(self) -> repositories.EventSettingsRepository:
        return repositories.EventSettingsRepository()

    @cached_property
    def events(self) -> repositories.EventRepository:
        return repositories.EventRepository()

    @cached_property
    def facilitators(self) -> repositories.FacilitatorRepository:
        return repositories.FacilitatorRepository()

    @cached_property
    def personal_data_fields(self) -> repositories.PersonalDataFieldRepository:
        return repositories.PersonalDataFieldRepository()

    @cached_property
    def proposal_categories(self) -> repositories.ProposalCategoryRepository:
        return repositories.ProposalCategoryRepository()

    @cached_property
    def session_fields(self) -> repositories.SessionFieldRepository:
        return repositories.SessionFieldRepository()

    @cached_property
    def sessions(self) -> repositories.SessionRepository:
        return repositories.SessionRepository()

    @cached_property
    def spaces(self) -> repositories.SpaceRepository:
        return repositories.SpaceRepository()

    @cached_property
    def spheres(self) -> repositories.SphereRepository:
        return repositories.SphereRepository()

    @cached_property
    def time_slots(self) -> repositories.TimeSlotRepository:
        return repositories.TimeSlotRepository()

    @cached_property
    def tracks(self) -> repositories.TrackRepository:
        return repositories.TrackRepository()

    @cached_property
    def encounters(self) -> repositories.EncounterRepository:
        return repositories.EncounterRepository()

    @cached_property
    def encounter_rsvps(self) -> repositories.EncounterRSVPRepository:
        return repositories.EncounterRSVPRepository()

    @cached_property
    def enrollment_configs(self) -> repositories.EnrollmentConfigRepository:
        return repositories.EnrollmentConfigRepository()

    @cached_property
    def personal_data_field_values(
        self,
    ) -> repositories.PersonalDataFieldValueRepository:
        return repositories.PersonalDataFieldValueRepository()

    @cached_property
    def schedule_change_logs(self) -> ScheduleChangeLogRepository:
        return ScheduleChangeLogRepository()
