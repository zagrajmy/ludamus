from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from ludamus.mills.errata import ErrataService
from ludamus.pacts.errata import ErratumKind
from ludamus.pacts.legacy import (
    NotFoundError,
    ScheduleChangeAction,
    ScheduleChangeLogDTO,
)

_EVENT_PK = 7
_PUBLISHED = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def _log(
    pk,
    action,
    *,
    session_id=1,
    at=_PUBLISHED,
    old_space=None,
    new_space=None,
    moved_from_id=None,
    acknowledgement_time=None,
    acknowledged_by_name="",
):
    return ScheduleChangeLogDTO(
        pk=pk,
        event_id=_EVENT_PK,
        session_id=session_id,
        session_title=f"Session {session_id}",
        user_id=3,
        user_name="Organizer",
        action=action,
        old_space_id=1 if old_space else None,
        old_space_name=old_space,
        new_space_id=2 if new_space else None,
        new_space_name=new_space,
        old_start_time=at if old_space else None,
        old_end_time=None,
        new_start_time=at if new_space else None,
        new_end_time=None,
        creation_time=at,
        moved_from_id=moved_from_id,
        acknowledgement_time=acknowledgement_time,
        acknowledged_by_name=acknowledged_by_name,
    )


@pytest.fixture(name="events")
def events_fixture():
    events = MagicMock()
    events.read.return_value = MagicMock(publication_time=_PUBLISHED)
    return events


@pytest.fixture(name="logs")
def logs_fixture():
    logs = MagicMock()
    logs.list_since.return_value = []
    return logs


@pytest.fixture(name="service")
def service_fixture(events, logs):
    return ErrataService(events=events, schedule_change_logs=logs)


class TestListForEvent:
    def test_unpublished_event_has_no_errata(self, service, events, logs):
        events.read.return_value = MagicMock(publication_time=None)

        assert not service.list_for_event(_EVENT_PK)
        logs.list_since.assert_not_called()

    def test_reads_the_log_from_publication_onwards(self, service, logs):
        service.list_for_event(_EVENT_PK)

        logs.list_since.assert_called_once_with(_EVENT_PK, _PUBLISHED)

    def test_an_assignment_reads_as_added(self, service, logs):
        logs.list_since.return_value = [
            _log(1, ScheduleChangeAction.ASSIGN, new_space="Room A")
        ]

        (erratum,) = service.list_for_event(_EVENT_PK)

        assert erratum.kind is ErratumKind.ADDED
        assert erratum.log_pks == [1]
        assert erratum.new_space_name == "Room A"

    def test_an_unassignment_reads_as_removed(self, service, logs):
        logs.list_since.return_value = [
            _log(1, ScheduleChangeAction.UNASSIGN, old_space="Room A")
        ]

        (erratum,) = service.list_for_event(_EVENT_PK)

        assert erratum.kind is ErratumKind.REMOVED
        assert erratum.old_space_name == "Room A"

    def test_a_revert_is_named_by_what_it_did_to_the_agenda(self, service, logs):
        logs.list_since.return_value = [
            _log(1, ScheduleChangeAction.REVERT, new_space="Room A")
        ]

        (erratum,) = service.list_for_event(_EVENT_PK)

        assert erratum.kind is ErratumKind.ADDED

    def test_the_two_rows_of_a_move_read_as_one_erratum(self, service, logs):
        logs.list_since.return_value = [
            _log(
                2,
                ScheduleChangeAction.ASSIGN,
                at=_PUBLISHED + timedelta(seconds=1),
                new_space="Room B",
                moved_from_id=1,
            ),
            _log(1, ScheduleChangeAction.UNASSIGN, old_space="Room A"),
        ]

        (erratum,) = service.list_for_event(_EVENT_PK)

        assert erratum.kind is ErratumKind.MOVED
        assert erratum.log_pks == [1, 2]
        assert erratum.old_space_name == "Room A"
        assert erratum.new_space_name == "Room B"

    def test_a_move_stays_one_erratum_however_long_the_write_took(self, service, logs):
        logs.list_since.return_value = [
            _log(
                2,
                ScheduleChangeAction.ASSIGN,
                at=_PUBLISHED + timedelta(hours=1),
                new_space="Room B",
                moved_from_id=1,
            ),
            _log(1, ScheduleChangeAction.UNASSIGN, old_space="Room A"),
        ]

        (erratum,) = service.list_for_event(_EVENT_PK)

        assert erratum.kind is ErratumKind.MOVED

    def test_rows_the_write_did_not_call_a_move_stay_separate(self, service, logs):
        logs.list_since.return_value = [
            _log(
                2,
                ScheduleChangeAction.ASSIGN,
                at=_PUBLISHED + timedelta(seconds=1),
                new_space="Room B",
            ),
            _log(1, ScheduleChangeAction.UNASSIGN, old_space="Room A"),
        ]

        errata = service.list_for_event(_EVENT_PK)

        assert [erratum.kind for erratum in errata] == [
            ErratumKind.ADDED,
            ErratumKind.REMOVED,
        ]

    def test_newest_change_comes_first(self, service, logs):
        logs.list_since.return_value = [
            _log(
                2,
                ScheduleChangeAction.ASSIGN,
                session_id=9,
                at=_PUBLISHED + timedelta(hours=1),
                new_space="Room B",
            ),
            _log(1, ScheduleChangeAction.ASSIGN, new_space="Room A"),
        ]

        errata = service.list_for_event(_EVENT_PK)

        assert [erratum.log_pks for erratum in errata] == [[2], [1]]

    def test_a_move_counts_as_announced_only_when_both_rows_are(self, service, logs):
        acknowledged = {
            "acknowledgement_time": _PUBLISHED,
            "acknowledged_by_name": "Press",
        }
        logs.list_since.return_value = [
            _log(
                2,
                ScheduleChangeAction.ASSIGN,
                at=_PUBLISHED + timedelta(seconds=1),
                new_space="Room B",
                moved_from_id=1,
                **acknowledged,
            ),
            _log(1, ScheduleChangeAction.UNASSIGN, old_space="Room A"),
        ]

        (erratum,) = service.list_for_event(_EVENT_PK)

        assert erratum.acknowledged_by_name is None

    def test_an_announced_change_names_who_announced_it(self, service, logs):
        logs.list_since.return_value = [
            _log(
                1,
                ScheduleChangeAction.ASSIGN,
                new_space="Room A",
                acknowledgement_time=_PUBLISHED,
                acknowledged_by_name="Press",
            )
        ]

        (erratum,) = service.list_for_event(_EVENT_PK)

        assert erratum.acknowledged_by_name == "Press"


class TestSetAcknowledged:
    def test_it_hands_the_repository_the_event_it_was_scoped_to(self, service, logs):
        logs.list_since.return_value = [
            _log(1, ScheduleChangeAction.ASSIGN, new_space="Room A")
        ]

        service.set_acknowledged(
            event_pk=_EVENT_PK, log_pks=[1], user_id=5, acknowledged=True
        )

        logs.set_acknowledged.assert_called_once_with(
            event_pk=_EVENT_PK, log_pks=[1], user_id=5, acknowledged=True
        )

    def test_a_row_the_page_never_listed_is_refused(self, service, logs):
        logs.list_since.return_value = [
            _log(1, ScheduleChangeAction.ASSIGN, new_space="Room A")
        ]

        with pytest.raises(NotFoundError):
            service.set_acknowledged(
                event_pk=_EVENT_PK, log_pks=[99], user_id=5, acknowledged=True
            )

        logs.set_acknowledged.assert_not_called()

    def test_a_row_from_before_publication_is_refused(self, service, events, logs):
        events.read.return_value = MagicMock(publication_time=None)

        with pytest.raises(NotFoundError):
            service.set_acknowledged(
                event_pk=_EVENT_PK, log_pks=[1], user_id=5, acknowledged=True
            )

        logs.set_acknowledged.assert_not_called()

    def test_half_a_move_is_refused(self, service, logs):
        logs.list_since.return_value = [
            _log(
                2,
                ScheduleChangeAction.ASSIGN,
                at=_PUBLISHED + timedelta(seconds=1),
                new_space="Room B",
                moved_from_id=1,
            ),
            _log(1, ScheduleChangeAction.UNASSIGN, old_space="Room A"),
        ]

        with pytest.raises(NotFoundError):
            service.set_acknowledged(
                event_pk=_EVENT_PK, log_pks=[2], user_id=5, acknowledged=True
            )

        logs.set_acknowledged.assert_not_called()

    def test_both_rows_of_a_move_are_accepted(self, service, logs):
        logs.list_since.return_value = [
            _log(
                2,
                ScheduleChangeAction.ASSIGN,
                at=_PUBLISHED + timedelta(seconds=1),
                new_space="Room B",
                moved_from_id=1,
            ),
            _log(1, ScheduleChangeAction.UNASSIGN, old_space="Room A"),
        ]

        service.set_acknowledged(
            event_pk=_EVENT_PK, log_pks=[1, 2], user_id=5, acknowledged=True
        )

        logs.set_acknowledged.assert_called_once_with(
            event_pk=_EVENT_PK, log_pks=[1, 2], user_id=5, acknowledged=True
        )

    def test_several_errata_are_accepted_in_one_batch(self, service, logs):
        logs.list_since.return_value = [
            _log(1, ScheduleChangeAction.ASSIGN, new_space="Room A"),
            _log(2, ScheduleChangeAction.UNASSIGN, session_id=2, old_space="Room B"),
        ]

        service.set_acknowledged(
            event_pk=_EVENT_PK, log_pks=[1, 2], user_id=5, acknowledged=True
        )

        logs.set_acknowledged.assert_called_once_with(
            event_pk=_EVENT_PK, log_pks=[1, 2], user_id=5, acknowledged=True
        )

    def test_a_batch_carrying_an_unlisted_row_is_refused_whole(self, service, logs):
        logs.list_since.return_value = [
            _log(1, ScheduleChangeAction.ASSIGN, new_space="Room A")
        ]

        with pytest.raises(NotFoundError):
            service.set_acknowledged(
                event_pk=_EVENT_PK, log_pks=[1, 99], user_id=5, acknowledged=True
            )

        logs.set_acknowledged.assert_not_called()

    def test_an_empty_batch_is_refused(self, service, logs):
        logs.list_since.return_value = [
            _log(1, ScheduleChangeAction.ASSIGN, new_space="Room A")
        ]

        with pytest.raises(NotFoundError):
            service.set_acknowledged(
                event_pk=_EVENT_PK, log_pks=[], user_id=5, acknowledged=True
            )

        logs.set_acknowledged.assert_not_called()
