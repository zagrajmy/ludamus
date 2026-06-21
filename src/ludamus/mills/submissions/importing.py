"""Proposal import: create Session rows from an integration's source responses."""

from secrets import choice
from typing import TYPE_CHECKING

from ludamus.mills.submissions.engine import ImportEngine
from ludamus.pacts.submissions import ImportRepos, ProposalImportResult

if TYPE_CHECKING:
    from ludamus.pacts.chronology import EventIntegrationsServiceProtocol
    from ludamus.pacts.services import TransactionProtocol


class ProposalImportService:
    """Turn an integration's source responses into proposal Sessions."""

    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        event_integrations: EventIntegrationsServiceProtocol,
        repos: ImportRepos,
    ) -> None:
        self._transaction = transaction
        self._event_integrations = event_integrations
        self._engine = ImportEngine(event_integrations, repos, transaction)

    def run(
        self, *, sphere_id: int, event_id: int, integration_pk: int
    ) -> ProposalImportResult:
        settings = self._engine.settings(event_id, integration_pk)
        rows = self._event_integrations.fetch_responses(
            sphere_id=sphere_id, event_id=event_id, pk=integration_pk
        )
        indexed = list(enumerate(rows))
        with self._transaction.atomic():
            return self._engine.import_rows(
                sphere_id=sphere_id,
                event_id=event_id,
                integration_pk=integration_pk,
                settings=settings,
                indexed_rows=indexed,
            )

    def run_sample(
        self, *, sphere_id: int, event_id: int, integration_pk: int
    ) -> ProposalImportResult:
        # Import a single random response so the operator can eyeball one real
        # proposal before a full run floods the event with mismapped sessions.
        settings = self._engine.settings(event_id, integration_pk)
        rows = self._event_integrations.fetch_responses(
            sphere_id=sphere_id, event_id=event_id, pk=integration_pk
        )
        if not rows:
            return ProposalImportResult(created=0, fields_created=0)
        idx = choice(range(len(rows)))
        with self._transaction.atomic():
            return self._engine.import_rows(
                sphere_id=sphere_id,
                event_id=event_id,
                integration_pk=integration_pk,
                settings=settings,
                indexed_rows=[(idx, rows[idx])],
            )
