from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING

from django.conf import settings

from ludamus.inits.repositories import Repositories
from ludamus.inits.transaction import DjangoTransaction
from ludamus.links.encryption import FernetDecryptor, FernetEncryptor
from ludamus.links.google_docs import GoogleDocsProposalImporter
from ludamus.mills.chronology import (
    CFPPersonalDataFieldService,
    EventIntegrationsService,
    SessionSelfEditService,
)
from ludamus.mills.multiverse import (
    ConnectionsService,
    EventsService,
    SpherePanelService,
)
from ludamus.pacts.chronology import IntegrationImplementationId

if TYPE_CHECKING:
    from ludamus.pacts.chronology import IntegrationImplementation


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
    def sphere_panel(self) -> SpherePanelService:
        return SpherePanelService(self._repos.spheres, self._repos.events)

    @cached_property
    def session_self_edit(self) -> SessionSelfEditService:
        return SessionSelfEditService(
            self._transaction,
            self._repos.sessions,
            self._repos.session_fields,
            self._repos.spheres,
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
