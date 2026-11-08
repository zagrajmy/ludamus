from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ludamus.mills.panel_proposals import ProposalPageService
from ludamus.pacts.legacy import NotFoundError, SessionContentEditData
from ludamus.pacts.panel import (
    ProposalAssignmentsDTO,
    ProposalEdit,
    ProposalPanelRepos,
    ProposalRecordRepos,
)
from tests.unit.factories import FakeTransaction, session_dto

_EVENT_ID = 1
_PROPOSAL_ID = 5
_USER_ID = 9
_RPG = 3
_LARP = 4
_ANN = 7
_BOB = 8


def _by_event(rows):
    return {_EVENT_ID: rows}.__getitem__


def _read_by_event(pk, event_id):
    if (pk, event_id) != (_PROPOSAL_ID, _EVENT_ID):
        raise NotFoundError
    return session_dto(pk=_PROPOSAL_ID, category_id=_LARP)


def _ids(*pks):
    return [SimpleNamespace(pk=pk) for pk in pks]


@pytest.fixture(name="repos")
def _repos():
    sessions = MagicMock()
    sessions.read_by_event.side_effect = _read_by_event
    categories = MagicMock()
    categories.list_by_event.side_effect = _by_event(
        [SimpleNamespace(pk=_RPG, name="RPG"), SimpleNamespace(pk=_LARP, name="LARP")]
    )
    categories.list_session_field_requirements.side_effect = lambda pk: [f"req-{pk}"]
    facilitators = MagicMock()
    facilitators.list_by_event.side_effect = _by_event(_ids(_ANN, _BOB))
    tracks = MagicMock()
    tracks.list_by_event.side_effect = _by_event(_ids(_RPG, _LARP))
    time_slots = MagicMock()
    time_slots.list_by_event.side_effect = _by_event(_ids(1, 2))
    session_fields = MagicMock()
    session_fields.list_by_event.side_effect = _by_event(["field"])
    return ProposalPanelRepos(
        sessions=sessions,
        session_fields=session_fields,
        proposal_categories=categories,
        panel_settings=MagicMock(),
        facilitators=facilitators,
        tracks=tracks,
        time_slots=time_slots,
    )


@pytest.fixture(name="records")
def _records():
    personal_fields = MagicMock()
    personal_fields.list_by_event.side_effect = _by_event(_ids(11))
    return ProposalRecordRepos(
        agenda_items=MagicMock(),
        schedule_change_logs=MagicMock(),
        personal_data_fields=personal_fields,
        personal_data_field_values=MagicMock(),
    )


@pytest.fixture(name="content_edit")
def _content_edit():
    return MagicMock()


@pytest.fixture(name="personal_data")
def _personal_data():
    return MagicMock()


@pytest.fixture(name="service")
def _service(repos, records, content_edit, personal_data):
    return ProposalPageService(
        transaction=FakeTransaction(),
        repos=repos,
        records=records,
        content_edit=content_edit,
        personal_data=personal_data,
    )


class TestDetail:
    def test_gathers_the_proposals_category_tracks_and_people(self, service, repos):
        repos.sessions.read_track_ids.return_value = [_LARP]

        detail = service.detail(event_id=_EVENT_ID, proposal_id=_PROPOSAL_ID)

        assert detail.category_name == "LARP"
        assert [track.pk for track in detail.tracks] == [_LARP]
        assert detail.presenter is repos.sessions.read_presenter.return_value

    def test_a_proposal_without_a_category_reads_no_categories(self, service, repos):
        repos.sessions.read_by_event.side_effect = None
        repos.sessions.read_by_event.return_value = session_dto(pk=_PROPOSAL_ID)

        detail = service.detail(event_id=_EVENT_ID, proposal_id=_PROPOSAL_ID)

        assert detail.category_name is None
        repos.proposal_categories.list_by_event.assert_not_called()

    def test_a_foreign_proposal_is_not_found(self, service):
        with pytest.raises(NotFoundError):
            service.detail(event_id=_EVENT_ID, proposal_id=_PROPOSAL_ID + 1)


class TestFormFields:
    def test_a_requested_category_of_the_event_wins(self, service):
        fields = service.form_fields(
            event_id=_EVENT_ID, proposal_id=_PROPOSAL_ID, category_id=_RPG
        )

        assert fields.category.pk == _RPG
        assert fields.requirements == [f"req-{_RPG}"]
        assert fields.session_fields == ["field"]

    def test_a_foreign_category_falls_back_to_the_proposals_own(self, service):
        fields = service.form_fields(
            event_id=_EVENT_ID, proposal_id=_PROPOSAL_ID, category_id=99
        )

        assert fields.category.pk == _LARP

    def test_a_new_proposal_starts_in_the_first_category_with_no_answers(
        self, service, repos
    ):
        fields = service.form_fields(
            event_id=_EVENT_ID, proposal_id=None, category_id=None
        )

        assert (fields.proposal, fields.category.pk) == (None, _RPG)
        assert (fields.field_values, fields.session_fields) == ([], [])
        repos.sessions.read_field_values.assert_not_called()

    def test_an_event_without_categories_asks_for_no_fields(self, service, repos):
        repos.proposal_categories.list_by_event.side_effect = _by_event([])

        fields = service.form_fields(
            event_id=_EVENT_ID, proposal_id=None, category_id=None
        )

        assert (fields.category, fields.requirements) == (None, [])

    def test_a_foreign_proposal_is_not_found(self, service):
        with pytest.raises(NotFoundError):
            service.form_fields(
                event_id=_EVENT_ID, proposal_id=_PROPOSAL_ID + 1, category_id=None
            )


class TestForm:
    def test_an_edit_reads_the_assigned_facilitators_personal_data(
        self, service, repos, records
    ):
        repos.sessions.read_facilitators.return_value = _ids(_ANN)

        page = service.form(
            event_id=_EVENT_ID, proposal_id=_PROPOSAL_ID, category_id=None
        )

        values = records.personal_data_field_values.list_values_for_facilitators
        values.assert_called_once_with([_ANN], [11])
        assert page.personal_data_values is values.return_value
        assert [f.pk for f in page.facilitators] == [_ANN, _BOB]

    def test_a_create_reads_no_personal_data(self, service, records):
        page = service.form(event_id=_EVENT_ID, proposal_id=None, category_id=None)

        assert page.assigned == ProposalAssignmentsDTO()
        assert page.personal_data_fields == []
        assert page.personal_data_values == {}
        records.personal_data_fields.list_by_event.assert_not_called()


class TestUpdate:
    def test_ids_the_event_does_not_own_are_dropped(
        self, service, content_edit, personal_data
    ):
        entries = [{"field_id": 11}]

        service.update(
            event_id=_EVENT_ID,
            proposal_id=_PROPOSAL_ID,
            user_id=_USER_ID,
            edit=ProposalEdit(
                content=SessionContentEditData(
                    update={"title": "T"},
                    facilitator_ids=[_BOB, 99],
                    track_ids=None,
                    time_slot_ids=[2, 98],
                ),
                personal_data={_ANN: entries},
            ),
        )

        data = content_edit.apply.call_args.kwargs["data"]
        assert (data.facilitator_ids, data.track_ids, data.time_slot_ids) == (
            [_BOB],
            None,
            [2],
        )
        personal_data.update_personal_data.assert_called_once_with(
            event_id=_EVENT_ID, facilitator_id=_ANN, entries=entries, user_id=_USER_ID
        )

    def test_a_foreign_proposal_writes_nothing(
        self, service, content_edit, personal_data
    ):
        with pytest.raises(NotFoundError):
            service.update(
                event_id=_EVENT_ID,
                proposal_id=_PROPOSAL_ID + 1,
                user_id=_USER_ID,
                edit=ProposalEdit(
                    content=SessionContentEditData(update={"title": "T"}),
                    personal_data={_ANN: []},
                ),
            )

        content_edit.apply.assert_not_called()
        personal_data.update_personal_data.assert_not_called()


class TestSetFacilitators:
    def test_only_the_events_facilitators_are_assigned(self, service, repos):
        service.set_facilitators(
            event_id=_EVENT_ID, proposal_id=_PROPOSAL_ID, facilitator_ids=[_BOB, 99]
        )

        repos.sessions.set_facilitators.assert_called_once_with(_PROPOSAL_ID, [_BOB])

    def test_a_foreign_proposal_writes_nothing(self, service, repos):
        with pytest.raises(NotFoundError):
            service.set_facilitators(
                event_id=_EVENT_ID, proposal_id=_PROPOSAL_ID + 1, facilitator_ids=[_BOB]
            )

        repos.sessions.set_facilitators.assert_not_called()
