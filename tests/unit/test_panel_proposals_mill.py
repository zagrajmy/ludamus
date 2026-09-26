from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ludamus.mills.panel_proposals import ProposalPanelService
from ludamus.pacts import NotFoundError, SessionStatus
from ludamus.pacts.availability import AvailabilityDTO, DayPart
from ludamus.pacts.panel import (
    ProposalDraft,
    ProposalListQuery,
    ProposalPanelRepos,
    SourceRowIdMissingError,
)
from ludamus.pacts.services import DatabaseConstraintError

_NEW_PROPOSAL_ID = 42
_EXISTING_SESSION_ID = 99
_IDENT_LOOKUPS_ON_CONSTRAINT = 2


def _offered(part: DayPart) -> AvailabilityDTO:
    return AvailabilityDTO(day=date(2026, 6, 1), part=part)


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
    def service(
        self,
        sessions,
        session_fields,
        proposal_categories,
        panel_settings,
        facilitators,
        tracks,
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

    def test_create_writes_session_field_values_and_availability_together(
        self, service, sessions, session_fields, facilitators, tracks
    ):
        sessions.slug_exists.return_value = False
        sessions.create.return_value = _NEW_PROPOSAL_ID
        session_fields.list_by_event.return_value = [
            SimpleNamespace(pk=3, field_type="select", order=0, name="System")
        ]
        facilitators.list_by_event.return_value = [SimpleNamespace(pk=7)]
        tracks.list_by_event.return_value = [SimpleNamespace(pk=4)]

        proposal_id = service.create_proposal(
            event_id=1,
            draft=ProposalDraft(
                data={"title": "Dragon Heist", "event_id": 1},
                base_slug="dragon-heist",
                facilitator_ids=[7],
                field_values={3: "D&D 5e"},
                track_ids=[4],
                availability=[_offered(DayPart.EVENING)],
            ),
        )

        assert proposal_id == _NEW_PROPOSAL_ID
        sessions.create.assert_called_once_with(
            {
                "title": "Dragon Heist",
                "event_id": 1,
                "slug": "dragon-heist",
                "status": SessionStatus.PENDING,
            },
            facilitator_ids=[7],
        )
        sessions.save_field_values.assert_called_once_with(
            _NEW_PROPOSAL_ID,
            [{"session_id": _NEW_PROPOSAL_ID, "field_id": 3, "value": "D&D 5e"}],
        )
        sessions.set_availability.assert_called_once_with(
            _NEW_PROPOSAL_ID, [_offered(DayPart.EVENING)]
        )
        sessions.set_session_tracks.assert_called_once_with(_NEW_PROPOSAL_ID, [4])

    def test_create_rejects_foreign_event_id_in_draft(self, service, sessions):
        with pytest.raises(NotFoundError):
            service.create_proposal(
                event_id=1,
                draft=ProposalDraft(
                    data={"title": "Foreign", "event_id": 2}, base_slug="foreign"
                ),
            )

        sessions.create.assert_not_called()

    def test_create_rejects_foreign_facilitator(self, service, sessions, facilitators):
        facilitators.list_by_event.return_value = []

        with pytest.raises(NotFoundError):
            service.create_proposal(
                event_id=1,
                draft=ProposalDraft(
                    data={"title": "Bad host", "event_id": 1},
                    base_slug="bad-host",
                    facilitator_ids=[7],
                ),
            )

        sessions.create.assert_not_called()

    def test_create_skips_empty_field_values_and_slots(self, service, sessions):
        sessions.slug_exists.return_value = False
        sessions.create.return_value = _NEW_PROPOSAL_ID

        service.create_proposal(
            event_id=1, draft=ProposalDraft(data={"title": "Bare"}, base_slug="bare")
        )

        sessions.save_field_values.assert_not_called()
        sessions.set_availability.assert_not_called()

    def test_create_accepted_session_returns_existing_ident(self, service, sessions):
        sessions.find_id_by_ident.return_value = _EXISTING_SESSION_ID

        session_id = service.create_accepted_session(
            event_id=1,
            source_row_id="row-1",
            draft=ProposalDraft(data={"title": "Retry"}, base_slug="retry"),
        )

        assert session_id == _EXISTING_SESSION_ID
        sessions.create.assert_not_called()

    def test_create_accepted_session_creates_accepted_with_ident(
        self, service, sessions
    ):
        sessions.find_id_by_ident.return_value = None
        sessions.slug_exists.return_value = False
        sessions.create.return_value = _NEW_PROPOSAL_ID

        session_id = service.create_accepted_session(
            event_id=1,
            source_row_id="row-1",
            draft=ProposalDraft(data={"title": "New"}, base_slug="new"),
        )

        assert session_id == _NEW_PROPOSAL_ID
        sessions.create.assert_called_once_with(
            {
                "title": "New",
                "event_id": 1,
                "slug": "new",
                "status": SessionStatus.ACCEPTED,
                "ident": "row-1",
            },
            facilitator_ids=[],
        )

    def test_create_accepted_session_rejects_blank_source_row_id(
        self, service, sessions
    ):
        with pytest.raises(SourceRowIdMissingError):
            service.create_accepted_session(
                event_id=1,
                source_row_id="   ",
                draft=ProposalDraft(data={"title": "Blank"}, base_slug="blank"),
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
