"""Service-side infrastructure and navigation protocols.

Holds the cross-cutting protocols that describe how mills services are wired
and reached from gates: the transaction adapter and the flat
`request.services` namespace.
"""

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from ludamus.pacts.bookmarks import BookmarkServiceProtocol
    from ludamus.pacts.chronology import (
        EventIntegrationsServiceProtocol,
        PartySessionHistoryServiceProtocol,
        ProposalAcceptanceServiceProtocol,
        ProposalPanelServiceProtocol,
        ProposalStatusServiceProtocol,
        SessionConfirmationServiceProtocol,
        SessionContentEditServiceProtocol,
        SessionDeletionServiceProtocol,
        SessionModalServiceProtocol,
        SessionSelfEditServiceProtocol,
    )
    from ludamus.pacts.crowd import (
        ClaimServiceProtocol,
        CompanionsServiceProtocol,
        CrowdAuthServiceProtocol,
        ProfileServiceProtocol,
    )
    from ludamus.pacts.discounts import (
        DiscountsExportServiceProtocol,
        DiscountsServiceProtocol,
    )
    from ludamus.pacts.enrollment import (
        AnonymousEnrollmentServiceProtocol,
        EnrollmentServiceProtocol,
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
    from ludamus.pacts.party import PartyServiceProtocol
    from ludamus.pacts.printing import (
        PrintablesReminderServiceProtocol,
        PrintMaterialsServiceProtocol,
    )
    from ludamus.pacts.safety import EventBanServiceProtocol, ShadowbanServiceProtocol
    from ludamus.pacts.submissions import (
        CFPPersonalDataFieldServiceProtocol,
        FacilitatorPanelServiceProtocol,
        ImportFieldLayoutServiceProtocol,
        ImportLogServiceProtocol,
        PersonalDataFieldValueServiceProtocol,
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
    def personal_data_field_values(self) -> PersonalDataFieldValueServiceProtocol: ...
    @property
    def facilitator_panel(self) -> FacilitatorPanelServiceProtocol: ...
    @property
    def connections(self) -> ConnectionsServiceProtocol: ...
    @property
    def claims(self) -> ClaimServiceProtocol: ...
    @property
    def crowd_auth(self) -> CrowdAuthServiceProtocol: ...
    @property
    def profile(self) -> ProfileServiceProtocol: ...
    @property
    def companions(self) -> CompanionsServiceProtocol: ...
    @property
    def parties(self) -> PartyServiceProtocol: ...
    @property
    def party_session_history(self) -> PartySessionHistoryServiceProtocol: ...
    @property
    def session_modal(self) -> SessionModalServiceProtocol: ...
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
    def proposal_panel(self) -> ProposalPanelServiceProtocol: ...
    @property
    def proposal_status(self) -> ProposalStatusServiceProtocol: ...
    @property
    def proposal_acceptance(self) -> ProposalAcceptanceServiceProtocol: ...
    @property
    def waitlist_promotion(self) -> WaitlistPromotionServiceProtocol: ...
    @property
    def anonymous_enrollment(self) -> AnonymousEnrollmentServiceProtocol: ...
    @property
    def notifications(self) -> NotificationsServiceProtocol: ...
    @property
    def enrollment(self) -> EnrollmentServiceProtocol: ...
    @property
    def print_materials(self) -> PrintMaterialsServiceProtocol: ...
    @property
    def printables_reminder(self) -> PrintablesReminderServiceProtocol: ...
    @property
    def venues(self) -> VenuesServiceProtocol: ...
    @property
    def space_tree(self) -> SpaceTreeServiceProtocol: ...
    @property
    def shadowban(self) -> ShadowbanServiceProtocol: ...
    @property
    def event_bans(self) -> EventBanServiceProtocol: ...
    @property
    def bookmarks(self) -> BookmarkServiceProtocol: ...
    @property
    def proposals_import(self) -> ProposalImportServiceProtocol: ...
    @property
    def import_log(self) -> ImportLogServiceProtocol: ...
    @property
    def import_field_layout(self) -> ImportFieldLayoutServiceProtocol: ...
    @property
    def discounts(self) -> DiscountsServiceProtocol: ...
    @property
    def discounts_export(self) -> DiscountsExportServiceProtocol: ...
