from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ludamus.mills.panel_proposals import ProposalPanelService
from ludamus.pacts import SessionStatus
from ludamus.pacts.panel import ProposalDraft, ProposalListQuery

_NEW_PROPOSAL_ID = 42


class _FakeTransaction:
    @contextmanager
    def savepoint(self):
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
    def service(self, sessions, session_fields, proposal_categories, panel_settings):
        return ProposalPanelService(
            transaction=_FakeTransaction(),
            sessions=sessions,
            session_fields=session_fields,
            proposal_categories=proposal_categories,
            panel_settings=panel_settings,
        )

    def test_foreign_category_is_dropped(self, service, sessions):
        result = service.list_context(
            event_id=1, query=ProposalListQuery(category="999")
        )

        assert result.category_pk is None
        assert sessions.list_sessions_by_event.call_args[0][1]["category_pk"] is None

    def test_own_category_is_kept(self, service, sessions, proposal_categories):
        category = SimpleNamespace(pk=7)
        proposal_categories.list_by_event.return_value = [category]

        result = service.list_context(event_id=1, query=ProposalListQuery(category="7"))

        assert result.category_pk == category.pk
        filters = sessions.list_sessions_by_event.call_args[0][1]
        assert filters["category_pk"] == category.pk

    def test_scheduled_pseudo_status_filters_on_placement(self, service, sessions):
        result = service.list_context(
            event_id=1, query=ProposalListQuery(status="scheduled")
        )

        filters = sessions.list_sessions_by_event.call_args[0][1]
        assert result.status == "scheduled"
        assert filters["status"] is None
        assert filters["scheduled"] is True

    def test_real_status_excludes_scheduled(self, service, sessions):
        result = service.list_context(
            event_id=1, query=ProposalListQuery(status="accepted")
        )

        filters = sessions.list_sessions_by_event.call_args[0][1]
        assert result.status == "accepted"
        assert filters["status"] is SessionStatus.ACCEPTED
        assert filters["scheduled"] is False

    def test_unknown_status_shows_everything(self, service, sessions):
        result = service.list_context(
            event_id=1, query=ProposalListQuery(status="bogus")
        )

        filters = sessions.list_sessions_by_event.call_args[0][1]
        assert result.status is None
        assert filters["status"] is None
        assert filters["scheduled"] is None

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

    def test_sorts_by_each_secondary_key(self, service, sessions):
        first = SimpleNamespace(
            title="B",
            display_name="Zoe",
            category_name="Alpha",
            status="accepted",
            creation_time=datetime(2026, 1, 2, tzinfo=UTC),
        )
        second = SimpleNamespace(
            title="A",
            display_name="Amy",
            category_name="Beta",
            status="pending",
            creation_time=datetime(2026, 1, 1, tzinfo=UTC),
        )
        sessions.list_sessions_by_event.return_value = [first, second]

        by_host = service.list_context(event_id=1, query=ProposalListQuery(sort="host"))
        by_category = service.list_context(
            event_id=1, query=ProposalListQuery(sort="category")
        )
        by_status = service.list_context(
            event_id=1, query=ProposalListQuery(sort="status")
        )
        by_created = service.list_context(
            event_id=1, query=ProposalListQuery(sort="created")
        )

        assert [p.display_name for p in by_host.proposals] == ["Amy", "Zoe"]
        assert [p.category_name for p in by_category.proposals] == ["Alpha", "Beta"]
        assert [p.status for p in by_status.proposals] == ["accepted", "pending"]
        assert [p.creation_time for p in by_created.proposals] == [
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 2, tzinfo=UTC),
        ]

    @pytest.mark.parametrize(("session_ids", "field_ids"), (([], [1]), ([1], [])))
    def test_column_values_short_circuits_on_empty_ids(
        self, service, sessions, session_ids, field_ids
    ):
        result = service.column_values(session_ids=session_ids, field_ids=field_ids)

        assert result == {}
        sessions.list_field_values_for_sessions.assert_not_called()

    def test_sorts_by_valid_key_and_drops_invalid(self, service, sessions):
        banana = SimpleNamespace(
            title="Banana",
            category_name="",
            status="pending",
            creation_time=datetime(2026, 1, 1, tzinfo=UTC),
        )
        apple = SimpleNamespace(
            title="Apple",
            category_name="",
            status="pending",
            creation_time=datetime(2026, 1, 2, tzinfo=UTC),
        )
        sessions.list_sessions_by_event.return_value = [banana, apple]

        ascending = service.list_context(
            event_id=1, query=ProposalListQuery(sort="title")
        )
        descending = service.list_context(
            event_id=1, query=ProposalListQuery(sort="-title")
        )
        invalid = service.list_context(
            event_id=1, query=ProposalListQuery(sort="bogus")
        )

        assert [p.title for p in ascending.proposals] == ["Apple", "Banana"]
        assert [p.title for p in descending.proposals] == ["Banana", "Apple"]
        assert not invalid.sort
        assert [p.title for p in invalid.proposals] == ["Banana", "Apple"]

    def test_create_writes_session_field_values_and_slots_together(
        self, service, sessions
    ):
        sessions.slug_exists.return_value = False
        sessions.create.return_value = _NEW_PROPOSAL_ID

        proposal_id = service.create_proposal(
            event_id=1,
            draft=ProposalDraft(
                data={"title": "Dragon Heist"},
                base_slug="dragon-heist",
                facilitator_ids=[7],
                field_values={3: "D&D 5e"},
                time_slot_ids=[9],
            ),
        )

        assert proposal_id == _NEW_PROPOSAL_ID
        sessions.create.assert_called_once_with(
            {"title": "Dragon Heist", "slug": "dragon-heist"}, facilitator_ids=[7]
        )
        sessions.save_field_values.assert_called_once_with(
            _NEW_PROPOSAL_ID,
            [{"session_id": _NEW_PROPOSAL_ID, "field_id": 3, "value": "D&D 5e"}],
        )
        sessions.set_time_slots.assert_called_once_with(_NEW_PROPOSAL_ID, [9])

    def test_create_skips_empty_field_values_and_slots(self, service, sessions):
        sessions.slug_exists.return_value = False
        sessions.create.return_value = _NEW_PROPOSAL_ID

        service.create_proposal(
            event_id=1, draft=ProposalDraft(data={"title": "Bare"}, base_slug="bare")
        )

        sessions.save_field_values.assert_not_called()
        sessions.set_time_slots.assert_not_called()
