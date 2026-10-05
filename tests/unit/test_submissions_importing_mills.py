from contextlib import nullcontext
from datetime import UTC, datetime
from operator import itemgetter
from typing import TYPE_CHECKING

import pytest

from ludamus.mills.submissions.importing import ProposalImportService
from ludamus.pacts import SessionStatus
from ludamus.pacts.chronology import EventIntegrationDTO
from ludamus.pacts.submissions import (
    ImportLogEntryCreateData,
    ImportLogEntryDTO,
    ImportLogStatus,
    ImportRepos,
    ImportRow,
    ImportSettings,
    ProposalImportResult,
    QuestionTarget,
)

SPHERE_ID = 1
EVENT_ID = 4
INTEGRATION_PK = 3
_NOW = datetime(2026, 3, 1, 12, tzinfo=UTC)
_SETTINGS = ImportSettings(questions={"Title": QuestionTarget(to="session.title")})

if TYPE_CHECKING:
    from ludamus.pacts import SessionData


class _Transaction:
    @staticmethod
    def atomic():
        return nullcontext()

    @staticmethod
    def savepoint():
        return nullcontext()


class _Integrations:
    def __init__(self, *titles: str) -> None:
        self.integration = EventIntegrationDTO.model_construct(
            pk=INTEGRATION_PK, settings_json=_SETTINGS.model_dump_json()
        )
        self.rows = [ImportRow({"Title": title}) for title in titles]

    def get(self, event_id: int, pk: int) -> EventIntegrationDTO:
        return {(EVENT_ID, INTEGRATION_PK): self.integration}[event_id, pk]

    def fetch_responses(self, *, sphere_id: int, event_id: int, pk: int):
        return {(SPHERE_ID, EVENT_ID, INTEGRATION_PK): self.rows}[
            sphere_id, event_id, pk
        ]


class _Sessions:
    def __init__(self) -> None:
        self.created: list[SessionData] = []

    def create(self, session_data: SessionData, **links) -> int:
        self.created.append(session_data)
        return 100 + len(self.created)

    def slug_exists(self, event_id: int, slug: str) -> bool:
        return any(data.get("slug") == slug for data in self.created)


class _LogEntries:
    def __init__(self) -> None:
        self.entries: list[ImportLogEntryDTO] = []

    def upsert(self, data: ImportLogEntryCreateData) -> ImportLogEntryDTO:
        entry = ImportLogEntryDTO(
            pk=len(self.entries) + 1, attempted_at=_NOW, **data.model_dump()
        )
        self.entries.append(entry)
        return entry


@pytest.fixture(name="sessions")
def fixture_sessions():
    return _Sessions()


@pytest.fixture(name="log_entries")
def fixture_log_entries():
    return _LogEntries()


def _service(
    integrations: _Integrations, sessions: _Sessions, log_entries: _LogEntries
) -> ProposalImportService:
    return ProposalImportService(
        transaction=_Transaction(),
        event_integrations=integrations,
        repos=ImportRepos(
            sessions=sessions,
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


class TestRun:
    def test_imports_every_source_row(self, sessions, log_entries):
        service = _service(_Integrations("Cats", "Dogs"), sessions, log_entries)

        result = service.run(
            sphere_id=SPHERE_ID, event_id=EVENT_ID, integration_pk=INTEGRATION_PK
        )

        assert result == ProposalImportResult(created=2, fields_created=0)
        assert [data["title"] for data in sessions.created] == ["Cats", "Dogs"]
        assert [(e.row_index, e.status) for e in log_entries.entries] == [
            (0, ImportLogStatus.SUCCESS),
            (1, ImportLogStatus.SUCCESS),
        ]


class TestRunSample:
    def test_imports_nothing_when_the_source_is_empty(self, sessions, log_entries):
        service = _service(_Integrations(), sessions, log_entries)

        result = service.run_sample(
            sphere_id=SPHERE_ID, event_id=EVENT_ID, integration_pk=INTEGRATION_PK
        )

        assert result == ProposalImportResult(created=0, fields_created=0)
        assert sessions.created == []
        assert log_entries.entries == []

    def test_imports_exactly_the_one_row_it_drew(
        self, sessions, log_entries, monkeypatch
    ):
        monkeypatch.setattr("ludamus.mills.submissions.importing.choice", itemgetter(1))
        service = _service(_Integrations("Cats", "Dogs", "Owls"), sessions, log_entries)

        result = service.run_sample(
            sphere_id=SPHERE_ID, event_id=EVENT_ID, integration_pk=INTEGRATION_PK
        )

        assert result == ProposalImportResult(created=1, fields_created=0)
        assert sessions.created == [
            {
                "event_id": EVENT_ID,
                "status": SessionStatus.PENDING,
                "title": "Dogs",
                "description": "",
                "facilitator_name": "",
                "participants_limit": 0,
                "slug": "dogs",
            }
        ]
        [entry] = log_entries.entries
        assert (entry.row_index, entry.title, entry.session_id) == (1, "Dogs", 101)
