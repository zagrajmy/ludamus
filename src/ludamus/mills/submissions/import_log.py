"""Import-log operations: list entries, retry or reimport a logged row."""

import json
from typing import TYPE_CHECKING

from ludamus.mills.submissions.engine import ImportEngine
from ludamus.mills.submissions.mapping import (
    RowSkippedError,
    decode_response,
    extract_identity,
    locate_row,
)
from ludamus.pacts import NotFoundError
from ludamus.pacts.services import DatabaseConstraintError
from ludamus.pacts.submissions import (
    ImportLogEntryCreateData,
    ImportLogEntryDTO,
    ImportLogStatus,
    ImportRepos,
)

if TYPE_CHECKING:
    from ludamus.pacts.chronology import EventIntegrationsServiceProtocol
    from ludamus.pacts.services import TransactionProtocol


class ImportLogService:
    """Read and act on the per-row log of a proposal import."""

    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        event_integrations: EventIntegrationsServiceProtocol,
        repos: ImportRepos,
    ) -> None:
        self._transaction = transaction
        self._event_integrations = event_integrations
        self._repos = repos
        self._engine = ImportEngine(event_integrations, repos, transaction)

    def list_log_entries(
        self,
        *,
        event_id: int,
        pk: int,
        status: ImportLogStatus | None = None,
        search: str = "",
    ) -> list[ImportLogEntryDTO]:
        # Touch the integration to enforce event scoping before listing.
        self._event_integrations.get(event_id, pk)
        return self._repos.log_entries.list_for_integration(
            pk, status=status, search=search
        )

    def log_entry_for_session(self, session_pk: int) -> ImportLogEntryDTO | None:
        return self._repos.log_entries.for_session(session_pk)

    def retry_entry(self, *, sphere_id: int, event_id: int, entry_pk: int) -> bool:
        # Refetch the live responses (operator may have updated the recipe);
        # locate the row via the unique-key columns when set, otherwise by the
        # original row_index. Write a fresh log entry for the new attempt;
        # the original entry stays in the log as history.
        try:
            entry = self._repos.log_entries.read(entry_pk)
        except NotFoundError:
            return False
        try:
            integration = self._event_integrations.get(event_id, entry.integration_id)
        except NotFoundError:
            # entry belongs to an integration that's not in this event — refuse.
            return False
        if integration.pk != entry.integration_id:
            return False
        settings = self._engine.settings(event_id, integration.pk)
        rows = self._event_integrations.fetch_responses(
            sphere_id=sphere_id, event_id=event_id, pk=integration.pk
        )
        original_response = decode_response(entry.response_json)
        if (
            located := locate_row(
                rows=rows,
                response=original_response,
                settings=settings,
                fallback_index=entry.row_index,
            )
        ) is None:
            self._repos.log_entries.upsert(
                ImportLogEntryCreateData(
                    integration_id=integration.pk,
                    row_index=entry.row_index,
                    status=ImportLogStatus.SKIPPED,
                    reason="row no longer present in source",
                    response_json=entry.response_json,
                    title=entry.title,
                    display_name=entry.display_name,
                )
            )
            return False
        target_idx, target_row = located
        with self._transaction.atomic():
            result = self._engine.import_rows(
                event_id=event_id,
                integration_pk=integration.pk,
                settings=settings,
                indexed_rows=[(target_idx, target_row)],
            )
        # A duplicate counts as "reconciled": the log entry now points at the
        # existing session and no skip reason remains.
        return result.created + result.duplicates == 1

    def reimport_entry(self, *, sphere_id: int, event_id: int, entry_pk: int) -> bool:
        # Reassert the source row over the existing session: refetch live
        # responses, locate the row, update mapped fields + replace m2m links.
        # If the linked session was deleted (session_id = None from SET_NULL),
        # fall through to retry-style "create fresh".
        try:
            entry = self._repos.log_entries.read(entry_pk)
        except NotFoundError:
            return False
        try:
            integration = self._event_integrations.get(event_id, entry.integration_id)
        except NotFoundError:
            return False
        if integration.pk != entry.integration_id:
            return False
        if entry.session_id is None:
            return self.retry_entry(
                sphere_id=sphere_id, event_id=event_id, entry_pk=entry_pk
            )
        settings = self._engine.settings(event_id, integration.pk)
        rows = self._event_integrations.fetch_responses(
            sphere_id=sphere_id, event_id=event_id, pk=integration.pk
        )
        original_response = decode_response(entry.response_json)
        if (
            located := locate_row(
                rows=rows,
                response=original_response,
                settings=settings,
                fallback_index=entry.row_index,
            )
        ) is None:
            self._repos.log_entries.upsert(
                ImportLogEntryCreateData(
                    integration_id=integration.pk,
                    row_index=entry.row_index,
                    status=ImportLogStatus.SKIPPED,
                    reason="row no longer present in source",
                    response_json=entry.response_json,
                    title=entry.title,
                    display_name=entry.display_name,
                    session_id=entry.session_id,
                )
            )
            return False
        target_idx, target_row = located
        title, display_name = extract_identity(settings, target_row)
        with self._transaction.atomic():
            field_ids, _ = self._engine.provision_fields(event_id, settings)
            try:
                with self._transaction.savepoint():
                    self._engine.update_proposal(
                        event_id=event_id,
                        session_id=entry.session_id,
                        settings=settings,
                        row=target_row,
                        field_ids=field_ids,
                    )
            except (RowSkippedError, DatabaseConstraintError) as exc:
                self._repos.log_entries.upsert(
                    ImportLogEntryCreateData(
                        integration_id=integration.pk,
                        row_index=target_idx,
                        status=ImportLogStatus.SKIPPED,
                        reason=str(exc),
                        response_json=json.dumps(target_row.data, ensure_ascii=False),
                        title=title,
                        display_name=display_name,
                        session_id=entry.session_id,
                    )
                )
                return False
            self._repos.log_entries.upsert(
                ImportLogEntryCreateData(
                    integration_id=integration.pk,
                    row_index=target_idx,
                    status=ImportLogStatus.SUCCESS,
                    response_json=json.dumps(target_row.data, ensure_ascii=False),
                    title=title,
                    display_name=display_name,
                    session_id=entry.session_id,
                )
            )
        return True
