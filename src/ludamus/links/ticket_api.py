"""Resolves the ticketing API an event is configured to talk to."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import ValidationError

from ludamus.pacts.chronology import IntegrationKind, TicketingIntegrationImplementation
from ludamus.pacts.legacy import NotFoundError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pydantic import BaseModel

    from ludamus.pacts.chronology import (
        EventIntegrationsRepositoryProtocol,
        IntegrationImplementation,
        IntegrationImplementationId,
    )
    from ludamus.pacts.legacy import TicketAPIProtocol
    from ludamus.pacts.multiverse import (
        ConnectionsRepositoryProtocol,
        DecryptorProtocol,
    )

logger = logging.getLogger(__name__)


class _BoundTicketApi:
    """One event's ticketing implementation with its credentials attached."""

    def __init__(
        self,
        *,
        implementation: TicketingIntegrationImplementation,
        secret: bytes,
        config: BaseModel,
    ) -> None:
        self._implementation = implementation
        self._secret = secret
        self._config = config

    def fetch_membership_count(self, user_email: str) -> int:
        return self._implementation.fetch_membership_count(
            secret=self._secret, config=self._config, user_email=user_email
        )


class TicketApiResolver:
    """Turns an event's ticketing integration row into a usable API client.

    Every failure mode — no integration, unknown implementation, unparsable
    config, deleted connection, empty secret — resolves to None, so enrollment
    silently falls back to whatever user and domain configs already exist
    instead of erroring on an event that never wired up ticketing.
    """

    def __init__(
        self,
        integrations: EventIntegrationsRepositoryProtocol,
        connections: ConnectionsRepositoryProtocol,
        decryptor: DecryptorProtocol,
        registry: Mapping[IntegrationImplementationId, IntegrationImplementation],
    ) -> None:
        self._integrations = integrations
        self._connections = connections
        self._decryptor = decryptor
        self._registry = registry
        # One enrollment read asks per active window, and an enroll POST asks
        # again per party member; the answer cannot change within a request.
        self._cache: dict[int, TicketAPIProtocol | None] = {}

    def resolve(self, *, event_id: int, sphere_id: int) -> TicketAPIProtocol | None:
        if event_id not in self._cache:
            self._cache[event_id] = self._resolve(
                event_id=event_id, sphere_id=sphere_id
            )
        return self._cache[event_id]

    def _resolve(self, *, event_id: int, sphere_id: int) -> TicketAPIProtocol | None:
        for integration in self._integrations.list_for_event(
            event_id, IntegrationKind.TICKETING
        ):
            implementation = self._registry.get(integration.implementation)
            if not isinstance(implementation, TicketingIntegrationImplementation):
                continue
            try:
                config = implementation.config_model.model_validate_json(
                    integration.config_json
                )
            except ValidationError:
                logger.warning(
                    "Ticketing integration %d has an invalid config", integration.pk
                )
                continue
            try:
                blob = self._connections.read_secret(
                    sphere_id, integration.connection_id
                )
            except NotFoundError:
                logger.warning(
                    "Ticketing integration %d points at a missing connection",
                    integration.pk,
                )
                continue
            if not blob:
                continue
            return _BoundTicketApi(
                implementation=implementation,
                secret=self._decryptor.decrypt(blob),
                config=config,
            )
        return None
