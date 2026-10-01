import json
from datetime import UTC, datetime

import pytest

from ludamus.mills.submissions.import_log import ImportLogService
from ludamus.pacts import NotFoundError
from ludamus.pacts.chronology import EventIntegrationDTO
from ludamus.pacts.submissions import (
    ImportLogEntryCreateData,
    ImportLogEntryDTO,
    ImportLogStatus,
    ImportRepos,
    ImportRow,
    ImportSettings,
    QuestionTarget,
)

SPHERE_ID = 1
EVENT_ID = 4
INTEGRATION_PK = 3
_NOW = datetime(2026, 3, 1, 12, tzinfo=UTC)
_SETTINGS = ImportSettings(questions={"Title": QuestionTarget(to="session.title")})


class _Integrations:
    def __init__(self, rows: list[ImportRow] | None = None) -> None:
        self.integration = EventIntegrationDTO.model_construct(
            pk=INTEGRATION_PK,
            event_id=EVENT_ID,
            settings_json=_SETTINGS.model_dump_json(),
        )
        self.rows = rows or []
        self.served_pks = {INTEGRATION_PK}

    def get(self, event_id: int, pk: int) -> EventIntegrationDTO:
        if event_id != EVENT_ID or pk not in self.served_pks:
            raise NotFoundError
        return self.integration

    def fetch_responses(self, *, sphere_id: int, event_id: int, pk: int):
        return self.rows


class _LogEntries:
    def __init__(self, *entries: ImportLogEntryDTO) -> None:
        self.entries = list(entries)

    def upsert(self, data: ImportLogEntryCreateData) -> ImportLogEntryDTO:
        entry = ImportLogEntryDTO(
            pk=len(self.entries) + 1, attempted_at=_NOW, **data.model_dump()
        )
        self.entries.append(entry)
        return entry

    def list_for_integration(
        self, integration_pk: int, *, status: ImportLogStatus | None = None, search=""
    ) -> list[ImportLogEntryDTO]:
        return [
            entry
            for entry in self.entries
            if entry.integration_id == integration_pk
            and (status is None or entry.status == status)
            and search.lower() in entry.title.lower()
        ]

    def for_session(self, session_pk: int) -> ImportLogEntryDTO | None:
        return next((e for e in self.entries if e.session_id == session_pk), None)

    def read(self, pk: int) -> ImportLogEntryDTO:
        if (match := next((e for e in self.entries if e.pk == pk), None)) is None:
            raise NotFoundError
        return match


def _entry(
    pk: int,
    *,
    integration_id: int = INTEGRATION_PK,
    status: ImportLogStatus = ImportLogStatus.SUCCESS,
    title: str = "Talk",
    session_id: int | None = None,
    row_index: int = 0,
) -> ImportLogEntryDTO:
    return ImportLogEntryDTO(
        pk=pk,
        integration_id=integration_id,
        row_index=row_index,
        status=status,
        response_json=json.dumps({"Title": title}),
        title=title,
        session_id=session_id,
        attempted_at=_NOW,
    )


def _service(
    log_entries: _LogEntries, integrations: _Integrations | None = None
) -> ImportLogService:
    return ImportLogService(
        transaction=None,
        event_integrations=integrations or _Integrations(),
        repos=ImportRepos(
            sessions=None,
            session_fields=None,
            personal_fields=None,
            personal_data_field_values=None,
            time_slots=None,
            tracks=None,
            categories=None,
            facilitators=None,
            facilitator_change_logs=None,
            log_entries=log_entries,
        ),
    )


class TestListing:
    def test_lists_the_integration_entries_matching_status_and_search(self):
        service = _service(
            _LogEntries(
                _entry(1, title="Dragons"),
                _entry(2, title="Dragons", status=ImportLogStatus.SKIPPED),
                _entry(3, title="Cats"),
                _entry(4, title="Dragons", integration_id=8),
            )
        )

        entries = service.list_log_entries(
            event_id=EVENT_ID,
            pk=INTEGRATION_PK,
            status=ImportLogStatus.SUCCESS,
            search="drag",
        )

        assert [entry.pk for entry in entries] == [1]

    def test_lists_every_integration_entry_without_filters(self):
        service = _service(
            _LogEntries(
                _entry(1, title="Dragons"),
                _entry(2, title="Cats", status=ImportLogStatus.SKIPPED),
                _entry(3, title="Dragons", integration_id=8),
            )
        )

        entries = service.list_log_entries(event_id=EVENT_ID, pk=INTEGRATION_PK)

        assert [entry.pk for entry in entries] == [1, 2]

    def test_listing_an_integration_outside_the_event_raises(self):
        service = _service(_LogEntries(_entry(1)))

        with pytest.raises(NotFoundError):
            service.list_log_entries(event_id=EVENT_ID + 1, pk=INTEGRATION_PK)

    def test_finds_the_entry_that_created_a_session(self):
        service = _service(_LogEntries(_entry(1, session_id=100), _entry(2)))

        assert service.log_entry_for_session(100).pk == 1
        assert service.log_entry_for_session(101) is None


class TestRetryRefusals:
    def test_refuses_an_unknown_entry(self):
        service = _service(_LogEntries())

        assert (
            service.retry_entry(sphere_id=SPHERE_ID, event_id=EVENT_ID, entry_pk=9)
            is False
        )

    def test_refuses_an_entry_of_an_integration_outside_the_event(self):
        log_entries = _LogEntries(_entry(1, integration_id=8))
        service = _service(log_entries)

        refused = service.retry_entry(
            sphere_id=SPHERE_ID, event_id=EVENT_ID, entry_pk=1
        )

        assert refused is False
        assert len(log_entries.entries) == 1

    def test_refuses_when_the_service_hands_back_another_integration(self):
        integrations = _Integrations()
        integrations.served_pks.add(8)
        log_entries = _LogEntries(_entry(1, integration_id=8))
        service = _service(log_entries, integrations)

        refused = service.retry_entry(
            sphere_id=SPHERE_ID, event_id=EVENT_ID, entry_pk=1
        )

        assert refused is False
        assert len(log_entries.entries) == 1


class TestReimportRefusals:
    def test_refuses_an_unknown_entry(self):
        service = _service(_LogEntries())

        assert (
            service.reimport_entry(sphere_id=SPHERE_ID, event_id=EVENT_ID, entry_pk=9)
            is False
        )

    def test_refuses_an_entry_of_an_integration_outside_the_event(self):
        log_entries = _LogEntries(_entry(1, integration_id=8, session_id=100))
        service = _service(log_entries)

        refused = service.reimport_entry(
            sphere_id=SPHERE_ID, event_id=EVENT_ID, entry_pk=1
        )

        assert refused is False
        assert len(log_entries.entries) == 1

    def test_refuses_when_the_service_hands_back_another_integration(self):
        integrations = _Integrations()
        integrations.served_pks.add(8)
        log_entries = _LogEntries(_entry(1, integration_id=8, session_id=100))
        service = _service(log_entries, integrations)

        refused = service.reimport_entry(
            sphere_id=SPHERE_ID, event_id=EVENT_ID, entry_pk=1
        )

        assert refused is False
        assert len(log_entries.entries) == 1

    def test_logs_a_skip_keeping_the_session_link_when_the_row_is_gone(self):
        log_entries = _LogEntries(_entry(1, session_id=100, row_index=5))
        service = _service(log_entries, _Integrations(rows=[ImportRow({"Title": "X"})]))

        refused = service.reimport_entry(
            sphere_id=SPHERE_ID, event_id=EVENT_ID, entry_pk=1
        )

        assert refused is False
        skip = log_entries.entries[-1]
        assert (skip.status, skip.reason, skip.session_id, skip.row_index) == (
            ImportLogStatus.SKIPPED,
            "row no longer present in source",
            100,
            5,
        )
        assert (skip.title, skip.response_json) == ("Talk", '{"Title": "Talk"}')
