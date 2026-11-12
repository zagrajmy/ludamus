from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING

from django.conf import settings

from ludamus.inits.builders import (
    build_credentials_decryptor,
    build_credentials_encryptor,
    build_email_verification,
    build_encounter_guests,
    build_encounters,
    build_konwencik_export,
    build_listings,
    build_printables_reminder,
    build_sites,
    build_sphere_subscriptions,
    build_waitlist_promotion,
)
from ludamus.inits.dbos_scheduler import (
    announcement_fanout_scheduler,
    offer_expiry_scheduler,
    parley_membership_outbox,
    parley_revocation_outbox,
)
from ludamus.inits.parley import parley_message_reader
from ludamus.inits.repositories import Repositories
from ludamus.links.cache import CacheAuthorizationCodeStore, DjangoCache
from ludamus.links.client_metadata import HttpClientMetadataFetcher
from ludamus.links.db.django.encounter_invites import SignedReplyAddress
from ludamus.links.db.django.moderation_mail import DjangoModerationMailer
from ludamus.links.db.django.notifications import DjangoUserNotifier
from ludamus.links.db.django.transaction import DjangoTransaction
from ludamus.links.encryption import JwtSigner
from ludamus.links.google_forms import GoogleDocsProposalImporter
from ludamus.links.google_sheets import KonwencikSheetExporter
from ludamus.links.sklep_kapitularz import SklepKapitularzIntegration
from ludamus.mills.bookmarks import BookmarkService
from ludamus.mills.dashboard import DashboardService, SphereSubscriptionService
from ludamus.mills.discounts import DiscountsService
from ludamus.mills.encounter_replies import EncounterReplyService
from ludamus.mills.enrollment import (
    EnrollmentService,
    EnrollmentSettingsService,
    WaitlistPromotionService,
)
from ludamus.mills.enrollment_anonymous import AnonymousEnrollmentService
from ludamus.mills.enrollment_member import (
    MemberEnrollmentPeers,
    MemberEnrollmentService,
)
from ludamus.mills.errata import ErrataService
from ludamus.mills.event import (
    EventConfirmationsService,
    EventPanelService,
    EventsService,
    LandingService,
    PanelTimeSlotsService,
)
from ludamus.mills.event_schedule import EventScheduleService
from ludamus.mills.event_settings import EventSettingsService
from ludamus.mills.guild import GuildService
from ludamus.mills.integrations import (
    EventIntegrationsService,
    IntegrationImplementations,
)
from ludamus.mills.maps import EventMapsService
from ludamus.mills.mcp import McpAuthorizationService
from ludamus.mills.moderation import (
    ActiveRecipientsService,
    ChatReportIntakeService,
    ModerationDecisionService,
    NoticeService,
    StatementOfReasonsService,
)
from ludamus.mills.notifications import (
    NotificationsService,
    NotificationSubscriptionsService,
)
from ludamus.mills.panel_facilitators import FacilitatorPanelService
from ludamus.mills.panel_proposals import ProposalPageService, ProposalPanelService
from ludamus.mills.parley import ParleyRevocationService, ParleyService
from ludamus.mills.parley_conversations import ParleyConversationService
from ludamus.mills.party import PartyService
from ludamus.mills.party_history import PartySessionHistoryService
from ludamus.mills.printing import PrintablesReminderService, PrintMaterialsService
from ludamus.mills.proposal_categories import ProposalCategoriesService
from ludamus.mills.propose.field_layout import ImportFieldLayoutService
from ludamus.mills.propose.import_log import ImportLogService
from ludamus.mills.propose.importing import ProposalImportService
from ludamus.mills.propose.personal_data_fields import (
    CFPPersonalDataFieldService,
    PersonalDataFieldValueService,
)
from ludamus.mills.propose.proposal_category_settings import (
    ProposalCategorySettingsService,
)
from ludamus.mills.propose.session_fields import CFPSessionFieldService
from ludamus.mills.propose.wizard import ProposeSessionService
from ludamus.mills.safety import EventBanService, ShadowbanService
from ludamus.mills.session_modal import SessionModalService
from ludamus.mills.sessions import (
    ProposalAcceptanceService,
    ProposalStatusService,
    SessionConfirmationService,
    SessionContentEditService,
    SessionDeletionService,
    SessionSelfEditService,
)
from ludamus.mills.sphere import (
    AnnouncementsService,
    ConnectionsService,
    SitesService,
    SpherePanelService,
)
from ludamus.mills.tags import TagService
from ludamus.mills.team import SphereTeamService
from ludamus.mills.timetable import (
    ConflictDetectionService,
    TimetableOverviewService,
    TimetableService,
)
from ludamus.mills.tracks import TracksPanelService
from ludamus.mills.user import (
    ClaimService,
    CompanionsService,
    CrowdAuthService,
    EmailVerificationService,
    ProfileService,
)
from ludamus.mills.venues import SpaceTreeService, VenuesService
from ludamus.pacts.enrollment import EnrollmentRepos
from ludamus.pacts.event_settings import EventSettingsRepos
from ludamus.pacts.integrations import IntegrationImplementationId
from ludamus.pacts.panel import (
    FacilitatorPanelRepos,
    ProposalPanelRepos,
    ProposalRecordRepos,
)
from ludamus.pacts.propose import (
    ImportRepos,
    ProposalCategorySettingsRepos,
    ProposeRepos,
)
from ludamus.pacts.timetable import TimetableRepos
from ludamus.pacts.user import gravatar_url

if TYPE_CHECKING:
    from ludamus.mills.encounter import EncounterService
    from ludamus.mills.encounter_calendar import EncounterGuests
    from ludamus.mills.konwencik import KonwencikExportService
    from ludamus.mills.listing import ListingService
    from ludamus.pacts.integrations import (
        ImportIntegrationImplementation,
        IntegrationImplementation,
        TicketingIntegrationImplementation,
    )


class Services:
    """Lazy flat service namespace exposed on `request.services`."""

    def __init__(self) -> None:
        self._repos = Repositories()
        self._transaction = DjangoTransaction()

    @cached_property
    def parley(self) -> ParleyService:
        signing_private_key: str = settings.PARLEY_SIGNING_PRIVATE_KEY
        agent_host: str = settings.PARLEY_AGENT_HOST
        return ParleyService(
            repository=self._repos.parley,
            conversations=self._repos.parley_conversations,
            signer=JwtSigner(signing_private_key),
            messages=parley_message_reader(),
            agent_host=agent_host,
        )

    @cached_property
    def parley_conversations(self) -> ParleyConversationService:
        return ParleyConversationService(
            transaction=self._transaction,
            repository=self._repos.parley_conversations,
            outbox=parley_membership_outbox(),
        )

    @cached_property
    def parley_revocations(self) -> ParleyRevocationService:
        return ParleyRevocationService(
            repository=self._repos.parley,
            outbox=parley_revocation_outbox(),
            conversations=self._repos.parley_conversations,
            memberships=parley_membership_outbox(),
        )

    @cached_property
    def personal_data_fields(self) -> CFPPersonalDataFieldService:
        return CFPPersonalDataFieldService(
            transaction=self._transaction, fields=self._repos.personal_data_fields
        )

    @cached_property
    def session_fields(self) -> CFPSessionFieldService:
        return CFPSessionFieldService(
            transaction=self._transaction,
            fields=self._repos.session_fields,
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
                events=self._repos.events,
                facilitators=self._repos.facilitators,
                personal_data_fields=self._repos.personal_data_fields,
                personal_data_field_values=self._repos.personal_data_field_values,
                facilitator_change_logs=self._repos.facilitator_change_logs,
                panel_settings=self._repos.event_panel_settings,
                sessions=self._repos.sessions,
                users=self._repos.active_users,
                guilds=self._repos.guilds,
            ),
        )

    @cached_property
    def connections(self) -> ConnectionsService:
        return ConnectionsService(
            self._transaction, self._repos.connections, build_credentials_encryptor()
        )

    @cached_property
    def claims(self) -> ClaimService:
        return ClaimService(self._transaction, self._repos.claims)

    @cached_property
    def profile(self) -> ProfileService:
        return ProfileService(
            transaction=self._transaction,
            users=self._repos.active_users,
            avatar_url=gravatar_url,
        )

    @cached_property
    def companions(self) -> CompanionsService:
        return CompanionsService(self._transaction, self._repos.companions)

    @cached_property
    def email_verification(self) -> EmailVerificationService:
        return build_email_verification()

    @cached_property
    def crowd_auth(self) -> CrowdAuthService:
        return CrowdAuthService(
            transaction=self._transaction,
            users=self._repos.active_users,
            spheres=self._repos.spheres,
            claims=self.claims,
            subscriptions=self._repos.sphere_subscriptions,
            chat=self.parley_revocations,
        )

    @cached_property
    def guilds(self) -> GuildService:
        return GuildService(transaction=self._transaction, guilds=self._repos.guilds)

    @cached_property
    def sphere_team(self) -> SphereTeamService:
        return SphereTeamService(
            transaction=self._transaction, team=self._repos.sphere_team
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
    def event_schedule(self) -> EventScheduleService:
        return EventScheduleService(
            schedule=self._repos.event_schedule,
            windows=self._repos.enrollment_windows,
            session_fields=self._repos.session_fields,
        )

    @cached_property
    def session_modal(self) -> SessionModalService:
        return SessionModalService(
            transaction=self._transaction, sessions=self._repos.sessions
        )

    @cached_property
    def announcements(self) -> AnnouncementsService:
        return AnnouncementsService(
            self._transaction,
            self._repos.announcements,
            announcement_fanout_scheduler(),
        )

    @cached_property
    def events(self) -> EventsService:
        return EventsService(
            transaction=self._transaction,
            events=self._repos.events,
            spheres=self._repos.spheres,
            spaces=self._repos.space_tree,
            setup=self._repos.event_setup,
        )

    @cached_property
    def event_panel(self) -> EventPanelService:
        return EventPanelService(self._repos.events)

    @cached_property
    def errata(self) -> ErrataService:
        return ErrataService(
            events=self._repos.events,
            schedule_change_logs=self._repos.schedule_change_logs,
        )

    @cached_property
    def confirmations(self) -> EventConfirmationsService:
        return EventConfirmationsService(
            facilitators=self._repos.facilitators,
            agenda_items=self._repos.agenda_items,
            tracks=self._repos.tracks,
            sessions=self._repos.sessions,
        )

    @cached_property
    def event_settings(self) -> EventSettingsService:
        return EventSettingsService(
            transaction=self._transaction,
            repos=EventSettingsRepos(
                events=self._repos.events,
                event_proposal_settings=self._repos.event_proposal_settings,
                proposal_categories=self._repos.proposal_categories,
                session_fields=self._repos.session_fields,
            ),
        )

    @cached_property
    def panel_time_slots(self) -> PanelTimeSlotsService:
        return PanelTimeSlotsService(
            transaction=self._transaction,
            time_slots=self._repos.time_slots,
            events=self._repos.events,
        )

    @cached_property
    def print_materials(self) -> PrintMaterialsService:
        return PrintMaterialsService(
            self._repos.events,
            self._repos.spaces,
            self._repos.agenda_items,
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
        return SpaceTreeService(
            transaction=self._transaction,
            spaces=self._repos.space_tree,
            events=self._repos.events,
        )

    @cached_property
    def event_maps(self) -> EventMapsService:
        return EventMapsService(
            self._transaction, self._repos.event_maps, self._repos.spaces
        )

    @cached_property
    def mcp_authorization(self) -> McpAuthorizationService:
        return McpAuthorizationService(
            fetcher=HttpClientMetadataFetcher(),
            codes=CacheAuthorizationCodeStore(),
            spheres=self.sphere_panel,
            users=self._repos.active_users,
        )

    @cached_property
    def sphere_panel(self) -> SpherePanelService:
        return SpherePanelService(
            self._transaction,
            self._repos.spheres,
            self._repos.events,
            self._repos.encounters,
            self._repos.active_users,
            self.parley_revocations,
        )

    @cached_property
    def sites(self) -> SitesService:
        return build_sites()

    @cached_property
    def landing(self) -> LandingService:
        domains: tuple[str, ...] = settings.LANDING_CONVENTION_DOMAINS
        return LandingService(
            self._repos.landing_stats, cache=DjangoCache(), convention_domains=domains
        )

    @cached_property
    def dashboard(self) -> DashboardService:
        return DashboardService(self._repos.dashboard)

    @cached_property
    def sphere_subscriptions(self) -> SphereSubscriptionService:
        return build_sphere_subscriptions()

    @cached_property
    def session_content_edit(self) -> SessionContentEditService:
        return SessionContentEditService(
            transaction=self._transaction,
            sessions=self._repos.sessions,
            session_fields=self._repos.session_fields,
            content_change_logs=self._repos.content_change_logs,
            agenda_items=self._repos.agenda_items,
            waitlist_promotion=self.waitlist_promotion,
        )

    @cached_property
    def session_confirmation(self) -> SessionConfirmationService:
        return SessionConfirmationService(
            self._transaction, self._repos.agenda_items, self._repos.sessions
        )

    @cached_property
    def session_deletion(self) -> SessionDeletionService:
        return SessionDeletionService(
            self._transaction,
            self._repos.sessions,
            self._repos.agenda_items,
            self._repos.schedule_change_logs,
        )

    @cached_property
    def proposal_panel(self) -> ProposalPanelService:
        return ProposalPanelService(self._transaction, self._proposal_panel_repos)

    @cached_property
    def proposal_page(self) -> ProposalPageService:
        return ProposalPageService(
            transaction=self._transaction,
            repos=self._proposal_panel_repos,
            records=ProposalRecordRepos(
                agenda_items=self._repos.agenda_items,
                schedule_change_logs=self._repos.schedule_change_logs,
                personal_data_fields=self._repos.personal_data_fields,
                personal_data_field_values=self._repos.personal_data_field_values,
            ),
            content_edit=self.session_content_edit,
            personal_data=self.personal_data_field_values,
        )

    @cached_property
    def _proposal_panel_repos(self) -> ProposalPanelRepos:
        return ProposalPanelRepos(
            sessions=self._repos.sessions,
            session_fields=self._repos.session_fields,
            proposal_categories=self._repos.proposal_categories,
            panel_settings=self._repos.event_panel_settings,
            facilitators=self._repos.facilitators,
            tracks=self._repos.tracks,
            time_slots=self._repos.time_slots,
        )

    @cached_property
    def proposal_status(self) -> ProposalStatusService:
        return ProposalStatusService(
            transaction=self._transaction,
            sessions=self._repos.sessions,
            agenda_items=self._repos.agenda_items,
            notifier=DjangoUserNotifier(),
        )

    @cached_property
    def proposal_acceptance(self) -> ProposalAcceptanceService:
        return ProposalAcceptanceService(
            transaction=self._transaction,
            sessions=self._repos.sessions,
            agenda_items=self._repos.agenda_items,
            schedule_change_logs=self._repos.schedule_change_logs,
            active_users=self._repos.active_users,
            spheres=self._repos.spheres,
            notifier=DjangoUserNotifier(),
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
        return build_waitlist_promotion(offer_expiry_scheduler())

    @cached_property
    def anonymous_enrollment(self) -> AnonymousEnrollmentService:
        return AnonymousEnrollmentService(
            transaction=self._transaction,
            user_repository=self._repos.anonymous_users,
            enrollment_repository=self._repos.anonymous_enrollment,
            waitlist_promotion=self.waitlist_promotion,
        )

    @cached_property
    def notifications(self) -> NotificationsService:
        return NotificationsService(self._transaction, self._repos.notifications)

    @cached_property
    def notification_subscriptions(self) -> NotificationSubscriptionsService:
        return NotificationSubscriptionsService(
            self._transaction, self._repos.notification_subscriptions
        )

    @cached_property
    def enrollment_settings(self) -> EnrollmentSettingsService:
        return EnrollmentSettingsService(
            self._transaction, self._repos.enrollment_windows
        )

    @cached_property
    def proposal_category_settings(self) -> ProposalCategorySettingsService:
        return ProposalCategorySettingsService(
            self._transaction,
            ProposalCategorySettingsRepos(
                categories=self._repos.proposal_categories,
                session_fields=self._repos.session_fields,
                time_slots=self._repos.time_slots,
                sessions=self._repos.sessions,
            ),
        )

    @cached_property
    def enrollment(self) -> EnrollmentService:
        return EnrollmentService(
            transaction=self._transaction,
            repos=EnrollmentRepos(
                users=self._repos.active_users,
                anonymous_users=self._repos.anonymous_users,
                enrollment_configs=self._repos.enrollment_configs,
                participations=self._repos.enrollment_participations,
                ticket_api_resolver=self.event_integrations,
                windows=self._repos.enrollment_windows,
            ),
        )

    @cached_property
    def member_enrollment(self) -> MemberEnrollmentService:
        return MemberEnrollmentService(
            transaction=self._transaction,
            repository=self._repos.member_enrollment,
            peers=MemberEnrollmentPeers(
                enrollment=self.enrollment,
                waitlist_promotion=self.waitlist_promotion,
                shadowban=self.shadowban,
                parties=self.parties,
                event_bans=self.event_bans,
            ),
        )

    @cached_property
    def shadowban(self) -> ShadowbanService:
        return ShadowbanService(
            self._transaction, self._repos.shadowban, DjangoUserNotifier()
        )

    @cached_property
    def event_bans(self) -> EventBanService:
        return EventBanService(
            transaction=self._transaction,
            repo=self._repos.event_bans,
            chat=self.parley_revocations,
        )

    @cached_property
    def notices(self) -> NoticeService:
        return NoticeService(
            transaction=self._transaction,
            cases=self._repos.moderation_cases,
            notices=self._repos.content_notices,
            cache=DjangoCache(),
            mailer=DjangoModerationMailer(),
        )

    @cached_property
    def chat_report_intake(self) -> ChatReportIntakeService:
        return ChatReportIntakeService(
            transaction=self._transaction,
            cases=self._repos.moderation_cases,
            reports=self._repos.chat_reports,
            mailer=DjangoModerationMailer(),
        )

    @cached_property
    def statements_of_reasons(self) -> StatementOfReasonsService:
        return StatementOfReasonsService(
            transaction=self._transaction,
            cases=self._repos.moderation_cases,
            statements=self._repos.statements_of_reasons,
            mailer=DjangoModerationMailer(),
        )

    @cached_property
    def moderation_decisions(self) -> ModerationDecisionService:
        return ModerationDecisionService(
            transaction=self._transaction,
            cases=self._repos.moderation_cases,
            notices=self._repos.content_notices,
            reports=self._repos.chat_reports,
            statements=self.statements_of_reasons,
            mailer=DjangoModerationMailer(),
        )

    @cached_property
    def active_recipients(self) -> ActiveRecipientsService:
        return ActiveRecipientsService(repository=self._repos.active_recipients)

    @cached_property
    def bookmarks(self) -> BookmarkService:
        return BookmarkService(self._transaction, self._repos.bookmarks)

    @cached_property
    def discounts(self) -> DiscountsService:
        return DiscountsService(
            transaction=self._transaction,
            discounts=self._repos.discounts,
            facilitators=self._repos.facilitators,
            rules=self._repos.discount_rules,
            schedule=self._repos.agenda_items,
            facilitator_change_logs=self._repos.facilitator_change_logs,
        )

    @cached_property
    def proposal_categories(self) -> ProposalCategoriesService:
        return ProposalCategoriesService(
            self._transaction, self._repos.proposal_categories
        )

    @cached_property
    def tags(self) -> TagService:
        return TagService(self._transaction, self._repos.tags)

    @cached_property
    def listings(self) -> ListingService:
        return build_listings()

    @cached_property
    def konwencik_export(self) -> KonwencikExportService:
        return build_konwencik_export()

    @cached_property
    def encounters(self) -> EncounterService:
        return build_encounters(self.sites, self._encounter_guests)

    @cached_property
    def _encounter_guests(self) -> EncounterGuests:
        return build_encounter_guests(self.sites)

    @cached_property
    def encounter_replies(self) -> EncounterReplyService:
        return EncounterReplyService(
            transaction=self._transaction,
            encounters=self._repos.encounters,
            rsvps=self._repos.encounter_rsvps,
            users=self._repos.active_users,
            guests=self._encounter_guests,
            reply_addresses=SignedReplyAddress(),
            sites=self.sites,
        )

    @cached_property
    def _import_implementations(
        self,
    ) -> dict[IntegrationImplementationId, ImportIntegrationImplementation]:
        return {
            IntegrationImplementationId.GOOGLE_PROPOSAL_PULLER: (
                GoogleDocsProposalImporter()
            )
        }

    @cached_property
    def _ticketing_implementations(
        self,
    ) -> dict[IntegrationImplementationId, TicketingIntegrationImplementation]:
        return {
            IntegrationImplementationId.SKLEP_KAPITULARZ: SklepKapitularzIntegration()
        }

    @cached_property
    def _export_implementations(
        self,
    ) -> dict[IntegrationImplementationId, IntegrationImplementation]:
        return {
            IntegrationImplementationId.KONWENCIK_SHEET_PUSHER: KonwencikSheetExporter()
        }

    @cached_property
    def event_integrations(self) -> EventIntegrationsService:
        return EventIntegrationsService(
            transaction=self._transaction,
            integrations=self._repos.event_integrations,
            connections=self._repos.connections,
            decryptor=build_credentials_decryptor(),
            implementations=IntegrationImplementations(
                imports=self._import_implementations,
                ticketing=self._ticketing_implementations,
                exports=self._export_implementations,
            ),
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
            self._repos.facilitator_change_logs,
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
    def propose_session(self) -> ProposeSessionService:
        return ProposeSessionService(
            transaction=self._transaction,
            repos=ProposeRepos(
                events=self._repos.events,
                event_proposal_settings=self._repos.event_proposal_settings,
                categories=self._repos.proposal_categories,
                tracks=self._repos.tracks,
                sessions=self._repos.sessions,
                reusable_sessions=self._repos.reusable_sessions,
                session_fields=self._repos.session_fields,
                personal_fields=self._repos.personal_data_fields,
                personal_data_field_values=self._repos.personal_data_field_values,
                facilitators=self._repos.facilitators,
                users=self._repos.active_users,
            ),
            cache=DjangoCache(),
        )

    @cached_property
    def tracks_panel(self) -> TracksPanelService:
        return TracksPanelService(
            transaction=self._transaction,
            tracks=self._repos.tracks,
            spaces=self._repos.spaces,
            spheres=self._repos.spheres,
        )

    @cached_property
    def _timetable_repos(self) -> TimetableRepos:
        return TimetableRepos(
            events=self._repos.events,
            sessions=self._repos.sessions,
            agenda_items=self._repos.agenda_items,
            spaces=self._repos.spaces,
            time_slots=self._repos.time_slots,
            tracks=self._repos.tracks,
            schedule_change_logs=self._repos.schedule_change_logs,
        )

    @cached_property
    def timetable(self) -> TimetableService:
        return TimetableService(
            self._transaction,
            self._timetable_repos,
            categories=self._repos.proposal_categories,
        )

    @cached_property
    def timetable_conflicts(self) -> ConflictDetectionService:
        return ConflictDetectionService(self._timetable_repos)

    @cached_property
    def timetable_overview(self) -> TimetableOverviewService:
        return TimetableOverviewService(self._timetable_repos)

    @cached_property
    def import_field_layout(self) -> ImportFieldLayoutService:
        return ImportFieldLayoutService(
            transaction=self._transaction,
            event_integrations=self.event_integrations,
            repos=self._import_repos,
        )
