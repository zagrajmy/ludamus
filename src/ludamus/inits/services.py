from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING

from django.conf import settings

from ludamus.inits.dbos_offer_scheduler import DBOSOfferExpiryScheduler
from ludamus.inits.repositories import Repositories
from ludamus.inits.transaction import DjangoTransaction
from ludamus.links.db.django.notifications import DjangoUserNotifier
from ludamus.links.encryption import FernetDecryptor, FernetEncryptor
from ludamus.links.google_docs import GoogleDocsProposalImporter
from ludamus.links.scheduler import CronSweepOfferScheduler
from ludamus.mills.chronology import (
    CFPPersonalDataFieldService,
    EventIntegrationsService,
    SessionContentEditService,
    SessionSelfEditService,
)
from ludamus.mills.enrollment import NotificationsService, WaitlistPromotionService
from ludamus.mills.multiverse import (
    ConnectionsService,
    EventsService,
    SitesService,
    SpherePanelService,
)
from ludamus.mills.printing import PrintMaterialsService
from ludamus.mills.safety import EventBanService, ShadowbanService
from ludamus.mills.venues import VenuesService
from ludamus.pacts.chronology import IntegrationImplementationId

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
            self._transaction,
            self._repos.personal_data_fields,
            self._repos.proposal_categories,
        )

    @cached_property
    def connections(self) -> ConnectionsService:
        key: str = settings.CREDENTIALS_ENCRYPTION_KEY
        return ConnectionsService(
            self._transaction, self._repos.connections, FernetEncryptor(key)
        )

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
        )

    @cached_property
    def venues(self) -> VenuesService:
        return VenuesService(self._repos.venues, self._repos.areas)

    @cached_property
    def sphere_panel(self) -> SpherePanelService:
        return SpherePanelService(self._repos.spheres, self._repos.events)

    @cached_property
    def sites(self) -> SitesService:
        return SitesService(self._repos.spheres)

    @cached_property
    def session_content_edit(self) -> SessionContentEditService:
        return SessionContentEditService(
            self._transaction,
            self._repos.sessions,
            self._repos.session_fields,
            self._repos.content_change_logs,
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
        return WaitlistPromotionService(
            self._transaction,
            self._repos.participation_promotion,
            DjangoUserNotifier(),
            self._offer_expiry_scheduler(),
        )

    @staticmethod
    def _offer_expiry_scheduler() -> OfferExpirySchedulerProtocol:
        scheduler_kind: str = settings.OFFER_EXPIRY_SCHEDULER
        return (
            DBOSOfferExpiryScheduler()
            if scheduler_kind == "dbos"
            else CronSweepOfferScheduler()
        )

    @cached_property
    def notifications(self) -> NotificationsService:
        return NotificationsService(self._transaction, self._repos.notifications)

    @cached_property
    def shadowban(self) -> ShadowbanService:
        return ShadowbanService(
            self._transaction, self._repos.shadowban, DjangoUserNotifier()
        )

    @cached_property
    def event_bans(self) -> EventBanService:
        return EventBanService(self._transaction, self._repos.event_bans)

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
