"""Service-side infrastructure and navigation protocols.

Holds the cross-cutting protocols that describe how mills services are wired
and reached from gates: the transaction adapter and the flat
`request.services` namespace.
"""

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from ludamus.pacts.chronology import (
        CFPPersonalDataFieldServiceProtocol,
        EventIntegrationsServiceProtocol,
        SessionContentEditServiceProtocol,
        SessionSelfEditServiceProtocol,
    )
    from ludamus.pacts.enrollment import (
        NotificationsServiceProtocol,
        WaitlistPromotionServiceProtocol,
    )
    from ludamus.pacts.multiverse import (
        ConnectionsServiceProtocol,
        EventsServiceProtocol,
        SitesServiceProtocol,
        SpherePanelServiceProtocol,
    )
    from ludamus.pacts.printing import PrintMaterialsServiceProtocol
    from ludamus.pacts.safety import EventBanServiceProtocol, ShadowbanServiceProtocol
    from ludamus.pacts.venues import VenuesServiceProtocol


class TransactionProtocol(Protocol):
    @staticmethod
    def atomic() -> AbstractContextManager[None]: ...


class ServicesProtocol(Protocol):
    @property
    def personal_data_fields(self) -> CFPPersonalDataFieldServiceProtocol: ...
    @property
    def connections(self) -> ConnectionsServiceProtocol: ...
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
    def session_content_edit(self) -> SessionContentEditServiceProtocol: ...
    @property
    def waitlist_promotion(self) -> WaitlistPromotionServiceProtocol: ...
    @property
    def notifications(self) -> NotificationsServiceProtocol: ...
    @property
    def print_materials(self) -> PrintMaterialsServiceProtocol: ...
    @property
    def venues(self) -> VenuesServiceProtocol: ...
    @property
    def shadowban(self) -> ShadowbanServiceProtocol: ...
    @property
    def event_bans(self) -> EventBanServiceProtocol: ...
