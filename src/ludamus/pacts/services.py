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
        SessionSelfEditServiceProtocol,
    )
    from ludamus.pacts.multiverse import (
        ConnectionsServiceProtocol,
        EventsServiceProtocol,
        SpherePanelServiceProtocol,
    )


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
    def event_integrations(self) -> EventIntegrationsServiceProtocol: ...
    @property
    def session_self_edit(self) -> SessionSelfEditServiceProtocol: ...
