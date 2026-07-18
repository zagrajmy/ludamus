from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING

from django.conf import settings

from ludamus.inits.builders import build_printables_reminder, build_waitlist_promotion
from ludamus.inits.dbos_scheduler import DBOSOfferExpiryScheduler
from ludamus.inits.repositories import Repositories
from ludamus.inits.transaction import DjangoTransaction
from ludamus.links.db.django.notifications import DjangoUserNotifier
from ludamus.links.db.django.schedule_change_log import ScheduleChangeLogRepository
from ludamus.links.encryption import FernetDecryptor, FernetEncryptor
from ludamus.links.google_docs import GoogleDocsProposalImporter, GoogleSheetsWriter
from ludamus.links.gravatar import gravatar_url
from ludamus.links.scheduler import CronSweepOfferScheduler
from ludamus.links.ticket_api import MembershipApiClient
from ludamus.mills.bookmarks import BookmarkService
from ludamus.mills.chronology import (
    EventIntegrationsService,
    ProposalStatusService,
    SessionConfirmationService,
    SessionContentEditService,
    SessionDeletionService,
    SessionSelfEditService,
)
from ludamus.mills.crowd import (
    ClaimService,
    CompanionsService,
    CrowdAuthService,
    ProfileService,
)
from ludamus.mills.discounts import DiscountsExportService, DiscountsService
from ludamus.mills.enrollment import (
    AnonymousEnrollmentService,
    EnrollmentService,
    NotificationsService,
    WaitlistPromotionService,
)
from ludamus.mills.multiverse import (
    AnnouncementsService,
    ConnectionsService,
    EventsService,
    SitesService,
    SpherePanelService,
)
from ludamus.mills.party import PartyService
from ludamus.mills.party_history import PartySessionHistoryService
from ludamus.mills.printing import PrintablesReminderService, PrintMaterialsService
from ludamus.mills.safety import EventBanService, ShadowbanService
from ludamus.mills.session_modal import SessionModalService
from ludamus.mills.submissions.facilitator_panel import FacilitatorPanelService
from ludamus.mills.submissions.field_layout import ImportFieldLayoutService
from ludamus.mills.submissions.import_log import ImportLogService
from ludamus.mills.submissions.importing import ProposalImportService
from ludamus.mills.submissions.personal_data_fields import (
    CFPPersonalDataFieldService,
    PersonalDataFieldValueService,
)
from ludamus.mills.venues import SpaceTreeService, VenuesService
from ludamus.pacts.chronology import IntegrationImplementationId
from ludamus.pacts.enrollment import EnrollmentRepos
from ludamus.pacts.submissions import FacilitatorPanelRepos, ImportRepos

if TYPE_CHECKING:
    from ludamus.pacts.chronology import IntegrationImplementation
    from ludamus.pacts.enrollment import OfferExpirySchedulerProtocol


class Services:
    """Lazy flat service namespace exposed on `request.services`.

    Buckets will appear when the leaf count grows past ~12.
    """

    def __init__(self) -> None:
        self._repos = Repositories()
        self._transaction = DjangoTransaction()

    @cached_property
    def personal_data_fields(self) -> CFPPersonalDataFieldService:
        return CFPPersonalDataFieldService(
            transaction=self._transaction,
            fields=self._repos.personal_data_fields,
            categories=self._repos.proposal_categories,
        )

    @cached_property
    def personal_data_field_values(self) -> PersonalDataFieldValueService:
        return PersonalDataFieldValueService(
            transaction=self._transaction,
            facilitators=self._repos.facilitators,
            personal_data_field_values=self._repos.personal_data_field_values,
            personal_data_fields=self._repos.personal_data_fields,
            facilitator_change_logs=self._repos.facilitator_change_logs,
        )

    @cached_property
    def facilitator_panel(self) -> FacilitatorPanelService:
        return FacilitatorPanelService(
            self._transaction,
            FacilitatorPanelRepos(
                facilitators=self._repos.facilitators,
                personal_data_fields=self._repos.personal_data_fields,
                personal_data_field_values=self._repos.personal_data_field_values,
                facilitator_change_logs=self._repos.facilitator_change_logs,
                panel_settings=self._repos.event_panel_settings,
            ),
        )

    @cached_property
    def connections(self) -> ConnectionsService:
        key: str = settings.CREDENTIALS_ENCRYPTION_KEY
        return ConnectionsService(
            self._transaction, self._repos.connections, FernetEncryptor(key)
        )

    @cached_property
    def claims(self) -> ClaimService:
        return ClaimService(self._transaction, self._repos.claims)

    @cached_property
    def profile(self) -> ProfileService:
        return ProfileService(
            transaction=self._transaction,
            users=self._repos.active_users,
            participations=self._repos.profile_stats,
            avatar_url=gravatar_url,
        )

    @cached_property
    def companions(self) -> CompanionsService:
        return CompanionsService(self._transaction, self._repos.companions)

    @cached_property
    def crowd_auth(self) -> CrowdAuthService:
        return CrowdAuthService(
            transaction=self._transaction,
            users=self._repos.active_users,
            spheres=self._repos.spheres,
            claims=self.claims,
        )

    @cached_property
    def parties(self) -> PartyService:
        return PartyService(
            self._transaction, self._repos.parties, DjangoUserNotifier()
        )

    @cached_property
    def party_session_history(self) -> PartySessionHistoryService:
        return PartySessionHistoryService(
            transaction=self._transaction,
            parties=self._repos.parties,
            history=self._repos.party_session_history,
        )

    @cached_property
    def session_modal(self) -> SessionModalService:
        return SessionModalService(
            transaction=self._transaction, sessions=self._repos.sessions
        )

    @cached_property
    def announcements(self) -> AnnouncementsService:
        return AnnouncementsService(self._transaction, self._repos.announcements)

    @cached_property
    def events(self) -> EventsService:
        return EventsService(self._repos.events)

    @cached_property
    def print_materials(self) -> PrintMaterialsService:
        return PrintMaterialsService(
            self._repos.events,
            self._repos.spaces,
            self._repos.agenda_items,
            self._repos.time_slots,
            self._repos.tracks,
        )

    @cached_property
    def printables_reminder(self) -> PrintablesReminderService:
        return build_printables_reminder()

    @cached_property
    def venues(self) -> VenuesService:
        return VenuesService(self._repos.space_tree)

    @cached_property
    def space_tree(self) -> SpaceTreeService:
        return SpaceTreeService(self._transaction, self._repos.space_tree)

    @cached_property
    def sphere_panel(self) -> SpherePanelService:
        return SpherePanelService(
            self._transaction, self._repos.spheres, self._repos.events
        )

    @cached_property
    def sites(self) -> SitesService:
        return SitesService(self._repos.spheres, self._repos.spheres)

    @cached_property
    def session_content_edit(self) -> SessionContentEditService:
        return SessionContentEditService(
            self._transaction,
            self._repos.sessions,
            self._repos.session_fields,
            self._repos.content_change_logs,
        )

    @cached_property
    def session_confirmation(self) -> SessionConfirmationService:
        return SessionConfirmationService(
            self._transaction,
            self._repos.agenda_items,
            self._repos.sessions,
            self._repos.tracks,
        )

    @cached_property
    def session_deletion(self) -> SessionDeletionService:
        return SessionDeletionService(
            self._transaction,
            self._repos.sessions,
            self._repos.agenda_items,
            ScheduleChangeLogRepository(),
        )

    @cached_property
    def proposal_status(self) -> ProposalStatusService:
        return ProposalStatusService(
            transaction=self._transaction,
            sessions=self._repos.sessions,
            agenda_items=self._repos.agenda_items,
        )

    @cached_property
    def session_self_edit(self) -> SessionSelfEditService:
        return SessionSelfEditService(
            self._repos.sessions,
            self._repos.session_fields,
            self._repos.spheres,
            self.session_content_edit,
        )

    @cached_property
    def waitlist_promotion(self) -> WaitlistPromotionService:
        return build_waitlist_promotion(self._offer_expiry_scheduler())

    @cached_property
    def anonymous_enrollment(self) -> AnonymousEnrollmentService:
        return AnonymousEnrollmentService(
            transaction=self._transaction,
            user_repository=self._repos.anonymous_users,
            enrollment_repository=self._repos.anonymous_enrollment,
            waitlist_promotion=self.waitlist_promotion,
        )

    @staticmethod
    def _offer_expiry_scheduler() -> OfferExpirySchedulerProtocol:
        scheduler_mode: str = settings.SCHEDULER_MODE
        return (
            DBOSOfferExpiryScheduler()
            if scheduler_mode == "dbos"
            else CronSweepOfferScheduler()
        )

    @cached_property
    def notifications(self) -> NotificationsService:
        return NotificationsService(self._transaction, self._repos.notifications)

    @cached_property
    def enrollment(self) -> EnrollmentService:
        membership_check_interval: int = settings.MEMBERSHIP_API_CHECK_INTERVAL
        return EnrollmentService(
            transaction=self._transaction,
            repos=EnrollmentRepos(
                users=self._repos.active_users,
                anonymous_users=self._repos.anonymous_users,
                enrollment_configs=self._repos.enrollment_configs,
                participations=self._repos.enrollment_participations,
                ticket_api=MembershipApiClient(),
            ),
            membership_check_interval=membership_check_interval,
        )

    @cached_property
    def shadowban(self) -> ShadowbanService:
        return ShadowbanService(
            self._transaction, self._repos.shadowban, DjangoUserNotifier()
        )

    @cached_property
    def event_bans(self) -> EventBanService:
        return EventBanService(self._transaction, self._repos.event_bans)

    @cached_property
    def bookmarks(self) -> BookmarkService:
        return BookmarkService(self._transaction, self._repos.bookmarks)

    @cached_property
    def discounts(self) -> DiscountsService:
        return DiscountsService(self._transaction, self._repos.discounts)

    @cached_property
    def discounts_export(self) -> DiscountsExportService:
        key: str = settings.CREDENTIALS_ENCRYPTION_KEY
        return DiscountsExportService(
            discounts=self._repos.discounts,
            facilitators=self._repos.facilitators,
            connections=self._repos.connections,
            decryptor=FernetDecryptor(key),
            sheet_writer=GoogleSheetsWriter(),
        )

    @cached_property
    def event_integrations(self) -> EventIntegrationsService:
        key: str = settings.CREDENTIALS_ENCRYPTION_KEY
        registry: dict[IntegrationImplementationId, IntegrationImplementation] = {
            IntegrationImplementationId.GOOGLE_PROPOSAL_PULLER: (
                GoogleDocsProposalImporter()
            )
        }
        return EventIntegrationsService(
            self._transaction,
            self._repos.event_integrations,
            self._repos.connections,
            FernetDecryptor(key),
            registry,
        )

    @cached_property
    def _import_repos(self) -> ImportRepos:
        return ImportRepos(
            self._repos.sessions,
            self._repos.session_fields,
            self._repos.personal_data_fields,
            self._repos.personal_data_field_values,
            self._repos.time_slots,
            self._repos.tracks,
            self._repos.proposal_categories,
            self._repos.facilitators,
            self._repos.import_log_entries,
        )

    @cached_property
    def proposals_import(self) -> ProposalImportService:
        # The Chronology integrations service supplies both the saved recipe
        # (settings_json) and the raw source rows; Submissions interprets them
        # into proposals.
        return ProposalImportService(
            transaction=self._transaction,
            event_integrations=self.event_integrations,
            repos=self._import_repos,
        )

    @cached_property
    def import_log(self) -> ImportLogService:
        return ImportLogService(
            transaction=self._transaction,
            event_integrations=self.event_integrations,
            repos=self._import_repos,
        )

    @cached_property
    def import_field_layout(self) -> ImportFieldLayoutService:
        return ImportFieldLayoutService(
            transaction=self._transaction,
            event_integrations=self.event_integrations,
            repos=self._import_repos,
        )
