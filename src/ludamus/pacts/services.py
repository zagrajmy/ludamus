"""Service-side infrastructure and navigation protocols.

Holds the cross-cutting protocols that describe how mills services are wired
and reached from gates: the transaction adapter and the flat
`request.services` namespace.
"""

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from ludamus.pacts.chronology import (
        EventIntegrationsServiceProtocol,
        ProposalStatusServiceProtocol,
        SessionConfirmationServiceProtocol,
        SessionContentEditServiceProtocol,
        SessionDeletionServiceProtocol,
        SessionSelfEditServiceProtocol,
    )
    from ludamus.pacts.discounts import DiscountsServiceProtocol
    from ludamus.pacts.enrollment import (
        NotificationsServiceProtocol,
        WaitlistPromotionServiceProtocol,
    )
    from ludamus.pacts.multiverse import (
        AnnouncementsServiceProtocol,
        ConnectionsServiceProtocol,
        EventsServiceProtocol,
        SitesServiceProtocol,
        SpherePanelServiceProtocol,
    )
    from ludamus.pacts.printing import PrintMaterialsServiceProtocol
    from ludamus.pacts.safety import EventBanServiceProtocol, ShadowbanServiceProtocol
    from ludamus.pacts.submissions import (
        CFPPersonalDataFieldServiceProtocol,
        ImportFieldLayoutServiceProtocol,
        ImportLogServiceProtocol,
        ProposalImportServiceProtocol,
    )
    from ludamus.pacts.venues import SpaceTreeServiceProtocol, VenuesServiceProtocol


class DatabaseConstraintError(Exception):
    """A DB integrity/data constraint was violated inside a `savepoint()`.

    Surfaced as a recoverable domain error so callers can record the failure
    and continue instead of letting a raw database exception abort the whole
    transaction.
    """


class TransactionProtocol(Protocol):
    @staticmethod
    def atomic() -> AbstractContextManager[None]: ...
    @staticmethod
    def savepoint() -> AbstractContextManager[None]: ...


class ServicesProtocol(Protocol):
    @property
    def personal_data_fields(self) -> CFPPersonalDataFieldServiceProtocol: ...
    @property
    def connections(self) -> ConnectionsServiceProtocol: ...
    @property
    def announcements(self) -> AnnouncementsServiceProtocol: ...
    @property
    def events(self) -> EventsServiceProtocol: ...
    @property
    def sphere_panel(self) -> SpherePanelServiceProtocol: ...
    @property
    def sites(self) -> SitesServiceProtocol: ...
    @property
    def event_integrations(self) -> EventIntegrationsServiceProtocol: ...
    @property
    def session_self_edit(self) -> SessionSelfEditServiceProtocol: ...
    @property
    def session_confirmation(self) -> SessionConfirmationServiceProtocol: ...
    @property
    def session_content_edit(self) -> SessionContentEditServiceProtocol: ...
    @property
    def session_deletion(self) -> SessionDeletionServiceProtocol: ...
    @property
    def proposal_status(self) -> ProposalStatusServiceProtocol: ...
    @property
    def waitlist_promotion(self) -> WaitlistPromotionServiceProtocol: ...
    @property
    def notifications(self) -> NotificationsServiceProtocol: ...
    @property
    def print_materials(self) -> PrintMaterialsServiceProtocol: ...
    @property
    def venues(self) -> VenuesServiceProtocol: ...
    @property
    def space_tree(self) -> SpaceTreeServiceProtocol: ...
    @property
    def shadowban(self) -> ShadowbanServiceProtocol: ...
    @property
    def event_bans(self) -> EventBanServiceProtocol: ...
    @property
    def proposals_import(self) -> ProposalImportServiceProtocol: ...
    @property
    def import_log(self) -> ImportLogServiceProtocol: ...
    @property
    def import_field_layout(self) -> ImportFieldLayoutServiceProtocol: ...
    @property
    def discounts(self) -> DiscountsServiceProtocol: ...
