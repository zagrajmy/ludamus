"""Per-event integration wiring: CRUD, connectivity checks and source pulls."""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import TypeAdapter, ValidationError

from ludamus.pacts import NotFoundError
from ludamus.pacts.chronology import (
    CheckOutcome,
    CheckResult,
    EventIntegrationCreateData,
    EventIntegrationDTO,
    EventIntegrationsRepositoryProtocol,
    EventIntegrationsServiceProtocol,
    EventIntegrationUpdateData,
    ImportIntegrationImplementation,
    IntegrationCheckRequest,
    IntegrationImplementation,
    IntegrationImplementationId,
    IntegrationKind,
    SourceQuestion,
    TicketingIntegrationImplementation,
)
from ludamus.pacts.legacy import MembershipAPIError
from ludamus.pacts.multiverse import DecryptionError
from ludamus.pacts.submissions import ImportRow, ImportSettings, QuestionTarget

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pydantic import BaseModel

    from ludamus.pacts.legacy import TicketAPIProtocol
    from ludamus.pacts.multiverse import (
        ConnectionsRepositoryProtocol,
        DecryptorProtocol,
    )
    from ludamus.pacts.services import TransactionProtocol

_SOURCE_QUESTIONS_ADAPTER = TypeAdapter(list[SourceQuestion])

logger = logging.getLogger(__name__)


class IntegrationImplementationNotFoundError(Exception):
    """Raised when the registry has no implementation for an identifier."""


@dataclass(frozen=True)
class _BoundImport:
    """One import integration's implementation with its credentials attached."""

    impl: ImportIntegrationImplementation
    config: BaseModel
    secret: bytes
    settings: ImportSettings


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


class _NoTicketApi:
    # No ticketing integration reads the same as an unreachable one: the
    # caller falls back to the stored config either way.
    @staticmethod
    def fetch_membership_count(_user_email: str) -> int:
        raise MembershipAPIError


@dataclass(frozen=True)
class IntegrationImplementations:
    """Every implementation the app ships, indexed by the kind it serves.

    One mapping per kind so the type system answers "can this row do
    fetch_questions" instead of an attribute-presence check.
    """

    imports: Mapping[IntegrationImplementationId, ImportIntegrationImplementation]
    ticketing: Mapping[IntegrationImplementationId, TicketingIntegrationImplementation]
    exports: Mapping[IntegrationImplementationId, IntegrationImplementation]

    def all(self) -> dict[IntegrationImplementationId, IntegrationImplementation]:
        # The kind-agnostic view, for the CRUD and check paths that need only
        # `kind` and `config_model`. Routing reads the typed mapping instead.
        return {**self.imports, **self.ticketing, **self.exports}


class EventIntegrationsService(EventIntegrationsServiceProtocol):
    """CRUD, check dispatch and credential binding for per-event integrations.

    `IntegrationImplementations` is composition-time data passed in from
    `inits/`; the mill never imports a concrete impl. An exporter carries no
    `fetch_*`, which is the empty result the import methods already return for
    an unknown identifier.
    """

    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        integrations: EventIntegrationsRepositoryProtocol,
        connections: ConnectionsRepositoryProtocol,
        decryptor: DecryptorProtocol,
        implementations: IntegrationImplementations,
    ) -> None:
        self._transaction = transaction
        self._integrations = integrations
        self._connections = connections
        self._decryptor = decryptor
        self._implementations = implementations
        # One enrollment read asks per active window, and an enroll POST asks
        # again per party member; the answer cannot change within a request.
        self._ticket_api_cache: dict[int, TicketAPIProtocol] = {}

    @property
    def _registry(self) -> dict[IntegrationImplementationId, IntegrationImplementation]:
        return self._implementations.all()

    def list_implementations(
        self, kind: IntegrationKind
    ) -> dict[IntegrationImplementationId, IntegrationImplementation]:
        return {
            impl_id: impl
            for impl_id, impl in self._registry.items()
            if impl.kind == kind
        }

    def list_all_implementations(
        self,
    ) -> dict[IntegrationImplementationId, IntegrationImplementation]:
        return dict(self._registry)

    def list_for_event(
        self, event_id: int, kind: IntegrationKind | None = None
    ) -> list[EventIntegrationDTO]:
        return self._integrations.list_for_event(event_id, kind)

    def get(self, event_id: int, pk: int) -> EventIntegrationDTO:
        return self._integrations.get(event_id, pk)

    def create(
        self, sphere_id: int, event_id: int, data: EventIntegrationCreateData
    ) -> EventIntegrationDTO:
        self._require_implementation(data["implementation"], data["kind"])
        # Raises NotFoundError if the connection isn't in this sphere.
        self._connections.get(sphere_id, data["connection_id"])
        with self._transaction.atomic():
            return self._integrations.create(event_id, data)

    def update(
        self, sphere_id: int, event_id: int, pk: int, data: EventIntegrationUpdateData
    ) -> EventIntegrationDTO:
        self._connections.get(sphere_id, data["connection_id"])
        with self._transaction.atomic():
            return self._integrations.update(event_id, pk, data)

    def delete(self, event_id: int, pk: int) -> None:
        with self._transaction.atomic():
            self._integrations.delete(event_id, pk)

    def fetch_questions(
        self, *, sphere_id: int, event_id: int, pk: int
    ) -> list[SourceQuestion]:
        bound = self._bind_import(sphere_id=sphere_id, event_id=event_id, pk=pk)
        if bound is None:
            return []
        return bound.impl.fetch_questions(
            secret=bound.secret,
            config=bound.config,
            header_row=bound.settings.header_row,
        )

    def get_cached_questions(self, event_id: int, pk: int) -> list[SourceQuestion]:
        integration = self._integrations.get(event_id, pk)
        raw = integration.questions_snapshot_json or "[]"
        try:
            return _SOURCE_QUESTIONS_ADAPTER.validate_json(raw)
        except ValidationError:
            return []

    def populate_questions_snapshot(
        self, *, sphere_id: int, event_id: int, pk: int
    ) -> list[SourceQuestion]:
        # Transparent first-load cache fill: live-fetches and writes the
        # snapshot, but leaves `settings.questions` (including confirmed
        # flags) untouched. Use `refetch_questions` for the operator-driven
        # action that also resets confirmations.
        questions = self.fetch_questions(sphere_id=sphere_id, event_id=event_id, pk=pk)
        snapshot = _SOURCE_QUESTIONS_ADAPTER.dump_json(questions).decode()
        headers = self.fetch_headers(sphere_id=sphere_id, event_id=event_id, pk=pk)
        integration = self._integrations.get(event_id, pk)
        settings = ImportSettings.model_validate_json(integration.settings_json or "{}")
        with self._transaction.atomic():
            self._integrations.update_questions_snapshot(
                event_id=event_id, pk=pk, questions_snapshot_json=snapshot
            )
            # Only overwrite on a successful read: a transient Sheets failure
            # returns [] and must not wipe the columns the run tab offers.
            if headers and headers != settings.sheet_headers:
                settings.sheet_headers = headers
                self._integrations.update_settings(
                    event_id=event_id, pk=pk, settings_json=settings.model_dump_json()
                )
        return questions

    def fetch_headers(self, *, sphere_id: int, event_id: int, pk: int) -> list[str]:
        bound = self._bind_import(sphere_id=sphere_id, event_id=event_id, pk=pk)
        if bound is None:
            return []
        return bound.impl.fetch_headers(
            secret=bound.secret,
            config=bound.config,
            header_row=bound.settings.header_row,
        )

    def refetch_questions(
        self, *, sphere_id: int, event_id: int, pk: int
    ) -> list[SourceQuestion]:
        # Per shape: regenerate question entries against the freshly fetched
        # form, drop every `confirmed` flag, preserve definitions untouched.
        # Questions that no longer exist in the form are dropped from
        # `settings.questions`; new ones land as missing entries (rendered
        # as unconfirmed by the summary).
        questions = self.populate_questions_snapshot(
            sphere_id=sphere_id, event_id=event_id, pk=pk
        )
        integration = self._integrations.get(event_id, pk)
        settings = ImportSettings.model_validate_json(integration.settings_json or "{}")
        seen = {q.title for q in questions}
        rebuilt: dict[str, QuestionTarget] = {}
        for title, target in settings.questions.items():
            if title in seen:
                target.confirmed = False
                rebuilt[title] = target
        settings.questions = rebuilt
        with self._transaction.atomic():
            self._integrations.update_settings(
                event_id=event_id, pk=pk, settings_json=settings.model_dump_json()
            )
        return questions

    def import_missing_questions(
        self, *, sphere_id: int, event_id: int, pk: int
    ) -> tuple[list[SourceQuestion], int]:
        # Refresh the snapshot but leave settings.questions untouched: existing
        # mappings (and their confirmations) survive, questions that disappeared
        # from the form stay in settings until the operator explicitly refetches.
        # Returns the fresh snapshot plus the count of questions that were not
        # yet present in settings.questions.
        integration = self._integrations.get(event_id, pk)
        before = ImportSettings.model_validate_json(integration.settings_json or "{}")
        questions = self.populate_questions_snapshot(
            sphere_id=sphere_id, event_id=event_id, pk=pk
        )
        missing = sum(1 for q in questions if q.title not in before.questions)
        return questions, missing

    def fetch_responses(
        self, *, sphere_id: int, event_id: int, pk: int
    ) -> list[ImportRow]:
        bound = self._bind_import(sphere_id=sphere_id, event_id=event_id, pk=pk)
        if bound is None:
            return []
        return bound.impl.fetch_responses(
            secret=bound.secret,
            config=bound.config,
            header_row=bound.settings.header_row,
        )

    def save_settings(self, *, event_id: int, pk: int, settings_json: str) -> None:
        with self._transaction.atomic():
            self._integrations.update_settings(
                event_id=event_id, pk=pk, settings_json=settings_json
            )

    def check(self, request: IntegrationCheckRequest) -> CheckResult:
        if (impl := self._registry.get(request.implementation)) is None:
            return CheckResult(
                outcome=CheckOutcome.NOT_FOUND,
                hint=f"Unknown implementation: {request.implementation}",
            )
        try:
            config = impl.config_model.model_validate_json(request.config_json)
        except ValidationError as exc:
            return CheckResult(
                outcome=CheckOutcome.NOT_FOUND, hint=f"Invalid config: {exc}"
            )
        try:
            blob = self._connections.read_secret(
                request.sphere_id, request.connection_id
            )
        except NotFoundError:
            return CheckResult(
                outcome=CheckOutcome.NOT_FOUND, hint="Connection not found."
            )
        plaintext = self._decryptor.decrypt(blob) if blob else b""
        return impl.check(plaintext, config)

    def resolve(self, *, event_id: int, sphere_id: int) -> TicketAPIProtocol:
        if event_id not in self._ticket_api_cache:
            self._ticket_api_cache[event_id] = self._resolve_ticket_api(
                event_id=event_id, sphere_id=sphere_id
            )
        return self._ticket_api_cache[event_id]

    def _resolve_ticket_api(
        self, *, event_id: int, sphere_id: int
    ) -> TicketAPIProtocol:
        # First usable integration wins: a row that cannot be bound is skipped
        # and the next one is tried, so one broken integration does not take
        # membership lookups down for the whole event.
        for integration in self._integrations.list_for_event(
            event_id, IntegrationKind.TICKETING
        ):
            impl = self._implementations.ticketing.get(integration.implementation)
            if impl is None:
                continue
            try:
                config = impl.config_model.model_validate_json(integration.config_json)
            except ValidationError:
                logger.warning(
                    "Ticketing integration %d has an invalid config", integration.pk
                )
                continue
            secret = self._ticketing_secret(
                sphere_id=sphere_id, integration=integration
            )
            if not secret:
                continue
            return _BoundTicketApi(implementation=impl, secret=secret, config=config)
        return _NoTicketApi()

    def _bind_import(
        self, *, sphere_id: int, event_id: int, pk: int
    ) -> _BoundImport | None:
        # Only import implementations answer the fetch_* calls; a ticketing or
        # export row reaching one would be a routing mistake, not a fetch with
        # no results.
        integration = self._integrations.get(event_id, pk)
        impl = self._implementations.imports.get(integration.implementation)
        if impl is None:
            return None
        blob = self._connections.read_secret(sphere_id, integration.connection_id)
        return _BoundImport(
            impl=impl,
            config=impl.config_model.model_validate_json(integration.config_json),
            secret=self._decryptor.decrypt(blob) if blob else b"",
            settings=ImportSettings.model_validate_json(
                integration.settings_json or "{}"
            ),
        )

    def _ticketing_secret(
        self, *, sphere_id: int, integration: EventIntegrationDTO
    ) -> bytes:
        # Every unusable secret is a warning and a skipped row, never a raise:
        # a broken ticketing row must not take participant enrollment down.
        try:
            blob = self._connections.read_secret(sphere_id, integration.connection_id)
        except NotFoundError:
            logger.warning(
                "Ticketing integration %d points at a missing connection",
                integration.pk,
            )
            return b""
        if not blob:
            logger.warning(
                "Ticketing integration %d uses a connection with no secret",
                integration.pk,
            )
            return b""
        try:
            return self._decryptor.decrypt(blob)
        except DecryptionError:
            logger.warning(
                "Ticketing integration %d has a secret that does not decrypt",
                integration.pk,
            )
            return b""

    def _require_implementation(
        self, identifier: IntegrationImplementationId, kind: IntegrationKind
    ) -> None:
        impl = self._registry.get(identifier)
        if impl is None or impl.kind != kind:
            raise IntegrationImplementationNotFoundError(identifier)
