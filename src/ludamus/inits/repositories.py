from functools import cached_property

from ludamus.links.db.django import repositories
from ludamus.links.db.django.agenda_item import AgendaItemRepository
from ludamus.links.db.django.bookmarks import BookmarkRepository
from ludamus.links.db.django.content_change_log import ContentChangeLogRepository
from ludamus.links.db.django.crowd import (
    ClaimRepository,
    CompanionRepository,
    ProfileStatsRepository,
    UserRepository,
)
from ludamus.links.db.django.enrollment import (
    AnonymousEnrollmentRepository,
    EnrollmentParticipationRepository,
    ParticipationPromotionRepository,
)
from ludamus.links.db.django.facilitator_change_log import (
    FacilitatorChangeLogRepository,
)
from ludamus.links.db.django.notifications import NotificationReadRepository
from ludamus.links.db.django.party import PartyRepository
from ludamus.links.db.django.printables import PrintablesReminderRepository
from ludamus.links.db.django.safety import EventBanRepository, ShadowbanRepository
from ludamus.pacts.crowd import UserType


class Repositories:
    """Lazy flat repository registry.

    Internal to inits — never imported from gates. Mills services receive
    specific repo protocols from this tree, not the tree itself. Buckets
    will appear when the leaf count grows past ~12.
    """

    @cached_property
    def personal_data_fields(self) -> repositories.PersonalDataFieldRepository:
        return repositories.PersonalDataFieldRepository()

    @cached_property
    def personal_data_field_values(
        self,
    ) -> repositories.PersonalDataFieldValueRepository:
        return repositories.PersonalDataFieldValueRepository()

    @cached_property
    def proposal_categories(self) -> repositories.ProposalCategoryRepository:
        return repositories.ProposalCategoryRepository()

    @cached_property
    def connections(self) -> repositories.ConnectionsRepository:
        return repositories.ConnectionsRepository()

    @cached_property
    def claims(self) -> ClaimRepository:
        return ClaimRepository()

    @cached_property
    def parties(self) -> PartyRepository:
        return PartyRepository()

    @cached_property
    def party_session_history(self) -> repositories.PartySessionHistoryRepository:
        return repositories.PartySessionHistoryRepository()

    @cached_property
    def announcements(self) -> repositories.AnnouncementsRepository:
        return repositories.AnnouncementsRepository()

    @cached_property
    def event_integrations(self) -> repositories.EventIntegrationsRepository:
        return repositories.EventIntegrationsRepository()

    @cached_property
    def spheres(self) -> repositories.SphereRepository:
        return repositories.SphereRepository()

    @cached_property
    def events(self) -> repositories.EventRepository:
        return repositories.EventRepository()

    @cached_property
    def sessions(self) -> repositories.SessionRepository:
        return repositories.SessionRepository()

    @cached_property
    def session_fields(self) -> repositories.SessionFieldRepository:
        return repositories.SessionFieldRepository()

    @cached_property
    def participation_promotion(self) -> ParticipationPromotionRepository:
        return ParticipationPromotionRepository()

    @cached_property
    def anonymous_enrollment(self) -> AnonymousEnrollmentRepository:
        return AnonymousEnrollmentRepository()

    @cached_property
    def enrollment_participations(self) -> EnrollmentParticipationRepository:
        return EnrollmentParticipationRepository()

    @cached_property
    def enrollment_configs(self) -> repositories.EnrollmentConfigRepository:
        return repositories.EnrollmentConfigRepository()

    @cached_property
    def active_users(self) -> UserRepository:
        return UserRepository(user_type=UserType.ACTIVE)

    @cached_property
    def anonymous_users(self) -> UserRepository:
        return UserRepository(user_type=UserType.ANONYMOUS)

    @cached_property
    def companions(self) -> CompanionRepository:
        return CompanionRepository()

    @cached_property
    def profile_stats(self) -> ProfileStatsRepository:
        return ProfileStatsRepository()

    @cached_property
    def notifications(self) -> NotificationReadRepository:
        return NotificationReadRepository()

    @cached_property
    def printables_reminders(self) -> PrintablesReminderRepository:
        return PrintablesReminderRepository()

    @cached_property
    def agenda_items(self) -> AgendaItemRepository:
        return AgendaItemRepository()

    @cached_property
    def content_change_logs(self) -> ContentChangeLogRepository:
        return ContentChangeLogRepository()

    @cached_property
    def facilitator_change_logs(self) -> FacilitatorChangeLogRepository:
        return FacilitatorChangeLogRepository()

    @cached_property
    def spaces(self) -> repositories.SpaceRepository:
        return repositories.SpaceRepository()

    @cached_property
    def space_tree(self) -> repositories.SpaceTreeRepository:
        return repositories.SpaceTreeRepository()

    @cached_property
    def time_slots(self) -> repositories.TimeSlotRepository:
        return repositories.TimeSlotRepository()

    @cached_property
    def tracks(self) -> repositories.TrackRepository:
        return repositories.TrackRepository()

    @cached_property
    def facilitators(self) -> repositories.FacilitatorRepository:
        return repositories.FacilitatorRepository()

    @cached_property
    def import_log_entries(self) -> repositories.ImportLogEntryRepository:
        return repositories.ImportLogEntryRepository()

    @cached_property
    def shadowban(self) -> ShadowbanRepository:
        return ShadowbanRepository()

    @cached_property
    def event_bans(self) -> EventBanRepository:
        return EventBanRepository()

    @cached_property
    def bookmarks(self) -> BookmarkRepository:
        return BookmarkRepository()

    @cached_property
    def discounts(self) -> repositories.DiscountRepository:
        return repositories.DiscountRepository()
