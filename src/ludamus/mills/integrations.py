"""Per-event integration wiring: CRUD, connectivity checks and source pulls."""

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
    IntegrationCheckRequest,
    IntegrationImplementation,
    IntegrationImplementationId,
    IntegrationKind,
    SourceQuestion,
)
from ludamus.pacts.submissions import ImportRow, ImportSettings, QuestionTarget

if TYPE_CHECKING:
    from ludamus.pacts.multiverse import (
        ConnectionsRepositoryProtocol,
        DecryptorProtocol,
    )
    from ludamus.pacts.services import TransactionProtocol

_SOURCE_QUESTIONS_ADAPTER = TypeAdapter(list[SourceQuestion])


class IntegrationImplementationNotFoundError(Exception):
    """Raised when the registry has no implementation for an identifier."""


class EventIntegrationsService(EventIntegrationsServiceProtocol):
    """CRUD + check dispatch for per-event integrations.

    The registry of `IntegrationImplementation`s is composition-time data
    passed in from `inits/`; the mill never imports a concrete impl.
    """

    def __init__(
        self,
        transaction: TransactionProtocol,
        integrations: EventIntegrationsRepositoryProtocol,
        connections: ConnectionsRepositoryProtocol,
        decryptor: DecryptorProtocol,
        registry: dict[IntegrationImplementationId, IntegrationImplementation],
    ) -> None:
        self._transaction = transaction
        self._integrations = integrations
        self._connections = connections
        self._decryptor = decryptor
        self._registry = registry

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
        integration = self._integrations.get(event_id, pk)
        if (impl := self._registry.get(integration.implementation)) is None:
            return []
        config = impl.config_model.model_validate_json(integration.config_json)
        settings = ImportSettings.model_validate_json(integration.settings_json or "{}")
        blob = self._connections.read_secret(sphere_id, integration.connection_id)
        plaintext = self._decryptor.decrypt(blob) if blob else b""
        return impl.fetch_questions(
            secret=plaintext, config=config, header_row=settings.header_row
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
        integration = self._integrations.get(event_id, pk)
        if (impl := self._registry.get(integration.implementation)) is None:
            return []
        config = impl.config_model.model_validate_json(integration.config_json)
        settings = ImportSettings.model_validate_json(integration.settings_json or "{}")
        blob = self._connections.read_secret(sphere_id, integration.connection_id)
        plaintext = self._decryptor.decrypt(blob) if blob else b""
        return impl.fetch_headers(
            secret=plaintext, config=config, header_row=settings.header_row
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
        integration = self._integrations.get(event_id, pk)
        if (impl := self._registry.get(integration.implementation)) is None:
            return []
        config = impl.config_model.model_validate_json(integration.config_json)
        settings = ImportSettings.model_validate_json(integration.settings_json or "{}")
        blob = self._connections.read_secret(sphere_id, integration.connection_id)
        plaintext = self._decryptor.decrypt(blob) if blob else b""
        return impl.fetch_responses(
            secret=plaintext, config=config, header_row=settings.header_row
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

    def _require_implementation(
        self, identifier: IntegrationImplementationId, kind: IntegrationKind
    ) -> None:
        impl = self._registry.get(identifier)
        if impl is None or impl.kind != kind:
            raise IntegrationImplementationNotFoundError(identifier)
