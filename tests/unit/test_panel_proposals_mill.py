from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest

from ludamus.mills.panel_proposals import ProposalPanelService
from ludamus.pacts import NotFoundError, SessionFieldValueData, SessionStatus
from ludamus.pacts.panel import (
    EmptyColumnSelectionError,
    ProposalDraft,
    ProposalListQuery,
    ProposalPanelRepos,
    SourceRowIdMissingError,
)
from ludamus.pacts.services import DatabaseConstraintError
from tests.unit.factories import FakeTransaction

_EXISTING_SESSION_ID = 99
_CREATED_SESSION_ID = 7
_EVENT_ID = 1


def _by_event(rows):
    return {_EVENT_ID: rows}.__getitem__


def _by_session(session_id, row):
    return lambda pk, event_id: {(session_id, _EVENT_ID): row}[pk, event_id]


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
        repo.list_by_event.side_effect = _by_event([])
        return repo

    @pytest.fixture
    def proposal_categories(self):
        repo = MagicMock()
        repo.list_by_event.side_effect = _by_event([])
        return repo

    @pytest.fixture
    def panel_settings(self):
        repo = MagicMock()
        repo.read_or_create.side_effect = _by_event(
            SimpleNamespace(proposal_columns=[])
        )
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
            FakeTransaction(),
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
        session_fields.list_by_event.side_effect = _by_event(
            [
                SimpleNamespace(pk=1, field_type="select", order=0, name="A"),
                SimpleNamespace(pk=2, field_type="text", order=1, name="B"),
            ]
        )

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
        assert sessions.find_id_by_ident.call_args_list == [call(1, "row-1")] * 2

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

        assert sessions.find_id_by_ident.call_args_list == [call(1, "row-1")] * 2
        sessions.create.assert_not_called()

    def test_known_category_and_scheduled_filter_reach_the_query(
        self, service, sessions, session_fields, proposal_categories, panel_settings
    ):
        category = SimpleNamespace(pk=5)
        select_field = SimpleNamespace(pk=1, field_type="select", order=0, name="A")
        proposal_categories.list_by_event.side_effect = _by_event([category])
        session_fields.list_by_event.side_effect = _by_event([select_field])
        panel_settings.read_or_create.side_effect = _by_event(
            SimpleNamespace(proposal_columns=["title"])
        )
        sessions.list_sessions_by_event.return_value = ["proposal"]

        result = service.list_context(
            event_id=1,
            query=ProposalListQuery(
                search="dragons",
                category="5",
                status="scheduled",
                track_pk=3,
                multi_tracks=True,
                sort="-title",
            ),
        )

        assert sessions.list_sessions_by_event.call_args == call(
            1,
            {
                "field_filters": None,
                "search": "dragons",
                "track_pk": 3,
                "multi_tracks": True,
                "category_pk": 5,
                "status": None,
                "scheduled": True,
                "sort": "-title",
            },
        )
        assert (
            result.proposals,
            result.filterable_fields,
            result.categories,
            result.category_pk,
            result.status,
            result.sort,
            [c.key for c in result.columns],
        ) == (
            ["proposal"],
            [select_field],
            [category],
            5,
            "scheduled",
            "-title",
            ["title"],
        )

    def test_real_status_excludes_scheduled_sessions(self, service, sessions):
        result = service.list_context(
            event_id=1, query=ProposalListQuery(category="7", status="accepted")
        )

        filters = sessions.list_sessions_by_event.call_args[0][1]
        assert (result.category_pk, result.status) == (None, "accepted")
        assert (filters["status"], filters["scheduled"]) == (
            SessionStatus.ACCEPTED,
            False,
        )

    def test_junk_status_shows_every_proposal(self, service, sessions):
        result = service.list_context(event_id=1, query=ProposalListQuery(status="all"))

        filters = sessions.list_sessions_by_event.call_args[0][1]
        assert result.status is None
        assert (filters["status"], filters["scheduled"]) == (None, None)

    def test_list_deleted_and_read_proposal_pass_through(self, service, sessions):
        sessions.list_deleted_by_event.side_effect = _by_event(["deleted"])
        sessions.read_by_event.side_effect = _by_session(3, "proposal")

        assert service.list_deleted(1) == ["deleted"]
        assert service.read_proposal(event_id=1, proposal_id=3) == "proposal"

    def test_column_values_skips_the_query_when_nothing_to_look_up(
        self, service, sessions
    ):
        sessions.list_field_values_for_sessions.return_value = {1: {"f": "v"}}

        assert service.column_values(session_ids=[], field_ids=[1]) == {}
        assert service.column_values(session_ids=[1], field_ids=[]) == {}
        assert service.column_values(session_ids=[1], field_ids=[1]) == {1: {"f": "v"}}
        assert sessions.list_field_values_for_sessions.call_args == call([1], [1])

    def test_columns_context_uses_the_saved_selection(
        self, service, session_fields, panel_settings
    ):
        session_fields.list_by_event.side_effect = _by_event(
            [SimpleNamespace(pk=4, order=0, name="A")]
        )
        panel_settings.read_or_create.side_effect = _by_event(
            SimpleNamespace(proposal_columns=["field_4", "title"])
        )

        context = service.columns_context(1)

        assert [c.key for c in context.chosen] == ["field_4", "title"]
        assert [c.key for c in context.available] == [
            "host",
            "category",
            "status",
            "created",
        ]

    def test_set_columns_refuses_an_empty_selection(self, service, panel_settings):
        with pytest.raises(EmptyColumnSelectionError):
            service.set_columns(event_id=1, columns=["bogus", "field_9"])

        panel_settings.update_proposal_columns.assert_not_called()

    def test_set_columns_saves_the_sanitized_keys(self, service, panel_settings):
        service.set_columns(event_id=1, columns=["status", "bogus", "status", "title"])

        panel_settings.update_proposal_columns.assert_called_once_with(
            1, ["status", "title"]
        )

    def test_create_accepted_session_requires_a_source_row_id(self, service, sessions):
        with pytest.raises(SourceRowIdMissingError):
            service.create_accepted_session(
                event_id=1,
                source_row_id="  ",
                draft=ProposalDraft(data={"title": "Race"}, base_slug="race"),
            )

        sessions.create.assert_not_called()

    def test_create_accepted_session_returns_the_existing_row(self, service, sessions):
        sessions.find_id_by_ident.side_effect = lambda event_id, ident: {
            (1, "row-1"): _EXISTING_SESSION_ID
        }[event_id, ident]

        session_id = service.create_accepted_session(
            event_id=1,
            source_row_id="row-1",
            draft=ProposalDraft(data={"title": "Race"}, base_slug="race"),
        )

        assert session_id == _EXISTING_SESSION_ID
        sessions.create.assert_not_called()

    def test_create_accepted_session_stores_ident_and_accepted_status(
        self, service, sessions
    ):
        sessions.find_id_by_ident.return_value = None
        sessions.slug_exists.return_value = False
        sessions.create.return_value = _CREATED_SESSION_ID

        session_id = service.create_accepted_session(
            event_id=1,
            source_row_id=" row-1 ",
            draft=ProposalDraft(data={"title": "Race"}, base_slug="race"),
        )

        assert session_id == _CREATED_SESSION_ID
        sessions.create.assert_called_once_with(
            {
                "title": "Race",
                "event_id": 1,
                "slug": "race",
                "status": SessionStatus.ACCEPTED,
                "ident": "row-1",
            },
            facilitator_ids=[],
        )

    def test_set_session_facilitator_name_scopes_to_the_event(self, service, sessions):
        sessions.read_by_event.side_effect = NotFoundError

        with pytest.raises(NotFoundError):
            service.set_session_facilitator_name(
                event_id=1, session_id=3, facilitator_name="Ala"
            )

        sessions.update.assert_not_called()

    def test_set_session_facilitator_name_updates_the_session(self, service, sessions):
        sessions.read_by_event.side_effect = _by_session(3, "proposal")

        service.set_session_facilitator_name(
            event_id=1, session_id=3, facilitator_name="Ala"
        )

        sessions.update.assert_called_once_with(3, {"facilitator_name": "Ala"})

    @pytest.mark.parametrize(
        "draft",
        (
            ProposalDraft(data={"title": "X"}, base_slug="x", field_values={9: "a"}),
            ProposalDraft(data={"title": "X"}, base_slug="x", facilitator_ids=[9]),
            ProposalDraft(data={"title": "X"}, base_slug="x", track_ids=[9]),
            ProposalDraft(data={"title": "X"}, base_slug="x", time_slot_ids=[9]),
            ProposalDraft(data={"title": "X", "category_id": 9}, base_slug="x"),
        ),
    )
    def test_create_rejects_references_outside_the_event(
        self, service, sessions, facilitators, tracks, time_slots, draft
    ):
        for repo in (facilitators, tracks, time_slots):
            repo.list_by_event.side_effect = _by_event([])

        with pytest.raises(NotFoundError):
            service.create_proposal(event_id=1, draft=draft)

        sessions.create.assert_not_called()

    def test_create_stores_answers_tracks_and_slots_and_caches_event_ids(
        self,
        service,
        sessions,
        session_fields,
        proposal_categories,
        facilitators,
        tracks,
        time_slots,
    ):
        session_fields.list_by_event.side_effect = _by_event(
            [SimpleNamespace(pk=1), SimpleNamespace(pk=2)]
        )
        proposal_categories.list_by_event.side_effect = _by_event(
            [SimpleNamespace(pk=5)]
        )
        facilitators.list_by_event.side_effect = _by_event([SimpleNamespace(pk=3)])
        tracks.list_by_event.side_effect = _by_event([SimpleNamespace(pk=4)])
        time_slots.list_by_event.side_effect = _by_event([SimpleNamespace(pk=6)])
        sessions.slug_exists.side_effect = lambda event_id, slug: (event_id, slug) == (
            1,
            "full",
        )
        sessions.create.return_value = 11
        draft = ProposalDraft(
            data={"title": "Full", "category_id": 5},
            base_slug="full",
            facilitator_ids=[3],
            field_values={1: "  ", 2: False},
            track_ids=[4],
            time_slot_ids=[6],
        )

        first = service.create_proposal(event_id=1, draft=draft)
        second = service.create_proposal(event_id=1, draft=draft)

        assert (first, second) == (11, 11)
        payload, kwargs = sessions.create.call_args_list[0]
        assert kwargs == {"facilitator_ids": [3]}
        assert payload[0]["status"] == SessionStatus.PENDING
        assert "ident" not in payload[0]
        assert payload[0]["slug"].startswith("full-")
        assert payload[0]["slug"] != "full"
        answered = [SessionFieldValueData(session_id=11, field_id=2, value=False)]
        assert sessions.save_field_values.call_args_list == [call(11, answered)] * 2
        sessions.set_session_tracks.assert_called_with(11, [4])
        sessions.set_time_slots.assert_called_with(11, [6])
        assert tracks.list_by_event.call_count == 1

    def test_create_without_answers_or_placement_writes_only_the_session(
        self, service, sessions, facilitators, tracks, time_slots
    ):
        for repo in (facilitators, tracks, time_slots):
            repo.list_by_event.side_effect = _by_event([])
        sessions.slug_exists.return_value = False
        sessions.create.return_value = _CREATED_SESSION_ID

        session_id = service.create_proposal(
            event_id=1,
            draft=ProposalDraft(data={"title": "Bare"}, base_slug="", field_values={}),
        )

        assert session_id == _CREATED_SESSION_ID
        assert sessions.create.call_args[0][0]["slug"] == "session"
        sessions.save_field_values.assert_not_called()
        sessions.set_session_tracks.assert_not_called()
        sessions.set_time_slots.assert_not_called()
