from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ludamus.mills.panel_proposals import ProposalPanelService
from ludamus.pacts import NotFoundError
from ludamus.pacts.panel import ProposalDraft, ProposalListQuery, ProposalPanelRepos
from ludamus.pacts.services import DatabaseConstraintError

_EXISTING_SESSION_ID = 99
_IDENT_LOOKUPS_ON_CONSTRAINT = 2


class _FakeTransaction:
    @contextmanager
    def savepoint(self):
        yield

    @contextmanager
    def atomic(self):
        yield


class TestProposalPanelService:
    @pytest.fixture
    def sessions(self):
        repo = MagicMock()
        repo.list_sessions_by_event.return_value = []
        repo.list_deleted_by_event.return_value = []
        return repo

    @pytest.fixture
    def session_fields(self):
        repo = MagicMock()
        repo.list_by_event.return_value = []
        return repo

    @pytest.fixture
    def proposal_categories(self):
        repo = MagicMock()
        repo.list_by_event.return_value = []
        return repo

    @pytest.fixture
    def panel_settings(self):
        repo = MagicMock()
        repo.read_or_create.return_value = SimpleNamespace(proposal_columns=[])
        return repo

    @pytest.fixture
    def facilitators(self):
        return MagicMock()

    @pytest.fixture
    def tracks(self):
        return MagicMock()

    @pytest.fixture
    def time_slots(self):
        return MagicMock()

    @pytest.fixture
    def service(
        self,
        sessions,
        session_fields,
        proposal_categories,
        panel_settings,
        facilitators,
        tracks,
        time_slots,
    ):
        return ProposalPanelService(
            _FakeTransaction(),
            ProposalPanelRepos(
                sessions=sessions,
                session_fields=session_fields,
                proposal_categories=proposal_categories,
                panel_settings=panel_settings,
                facilitators=facilitators,
                tracks=tracks,
                time_slots=time_slots,
            ),
        )

    def test_field_filters_guard_foreign_and_blank_values(
        self, service, sessions, session_fields
    ):
        session_fields.list_by_event.return_value = [
            SimpleNamespace(pk=1, field_type="select", order=0, name="A"),
            SimpleNamespace(pk=2, field_type="text", order=1, name="B"),
        ]

        service.list_context(
            event_id=1,
            query=ProposalListQuery(
                raw_field_filters={1: " D&D ", 2: "sneaky", 3: "foreign", 4: "  "}
            ),
        )

        filters = sessions.list_sessions_by_event.call_args[0][1]
        assert filters["field_filters"] == {1: "D&D"}

    @pytest.mark.parametrize("sort", ("field_999", "field_"))
    def test_unknown_sort_key_never_reaches_the_query(self, service, sessions, sort):
        result = service.list_context(event_id=1, query=ProposalListQuery(sort=sort))

        assert not result.sort
        assert sessions.list_sessions_by_event.call_args[0][1]["sort"] is None

    def test_create_rejects_foreign_event_id_in_draft(self, service, sessions):
        with pytest.raises(NotFoundError):
            service.create_proposal(
                event_id=1,
                draft=ProposalDraft(
                    data={"title": "Foreign", "event_id": 2}, base_slug="foreign"
                ),
            )

        sessions.create.assert_not_called()

    def test_create_accepted_session_recovers_from_constraint_error(
        self, service, sessions, monkeypatch
    ):
        sessions.find_id_by_ident.side_effect = [None, _EXISTING_SESSION_ID]
        monkeypatch.setattr(
            service,
            "_create_session",
            MagicMock(side_effect=DatabaseConstraintError("duplicate ident")),
        )

        session_id = service.create_accepted_session(
            event_id=1,
            source_row_id="row-1",
            draft=ProposalDraft(data={"title": "Race"}, base_slug="race"),
        )

        assert session_id == _EXISTING_SESSION_ID
        assert sessions.find_id_by_ident.call_count == _IDENT_LOOKUPS_ON_CONSTRAINT

    def test_create_accepted_session_reraises_when_ident_still_missing(
        self, service, sessions, monkeypatch
    ):
        sessions.find_id_by_ident.return_value = None
        monkeypatch.setattr(
            service,
            "_create_session",
            MagicMock(side_effect=DatabaseConstraintError("duplicate ident")),
        )

        with pytest.raises(DatabaseConstraintError):
            service.create_accepted_session(
                event_id=1,
                source_row_id="row-1",
                draft=ProposalDraft(data={"title": "Race"}, base_slug="race"),
            )

        assert sessions.find_id_by_ident.call_count == _IDENT_LOOKUPS_ON_CONSTRAINT
        sessions.create.assert_not_called()
