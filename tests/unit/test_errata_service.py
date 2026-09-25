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
    important=False,
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
        important=important,
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

    # Stands in for the repository's scoped read: the rows a batch names, plus
    # the other half of every move among them, out of the same seeded log.
    def erratum_rows(*, since, log_pks, **_):
        wanted = set(log_pks)
        window = [
            row for row in logs.list_since.return_value if row.creation_time >= since
        ]
        named = {
            row.pk for row in window if row.pk in wanted or row.moved_from_id in wanted
        }
        left_behind = {
            row.moved_from_id for row in window if row.pk in named and row.moved_from_id
        }
        return [row for row in window if row.pk in named | left_behind]

    logs.list_erratum_rows.side_effect = erratum_rows
    return logs


@pytest.fixture(name="service")
def service_fixture(events, logs):
    return ErrataService(events=events, schedule_change_logs=logs)


class TestListForEvent:
    def test_a_revert_is_named_by_what_it_did_to_the_agenda(self, service, logs):
        logs.list_since.return_value = [
            _log(1, ScheduleChangeAction.REVERT, new_space="Room A")
        ]

        (erratum,) = service.list_for_event(_EVENT_PK)

        assert erratum.kind is ErratumKind.ADDED

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

    def test_an_announced_important_change_sinks_below_the_backlog(self, service, logs):
        logs.list_since.return_value = [
            _log(
                2,
                ScheduleChangeAction.ASSIGN,
                session_id=9,
                at=_PUBLISHED + timedelta(hours=1),
                new_space="Room B",
            ),
            _log(
                1,
                ScheduleChangeAction.ASSIGN,
                new_space="Room A",
                important=True,
                acknowledgement_time=_PUBLISHED + timedelta(hours=2),
                acknowledged_by_name="Comms",
            ),
        ]

        errata = service.list_for_event(_EVENT_PK)

        assert [erratum.log_pks for erratum in errata] == [[2], [1]]

    def test_a_move_is_important_when_either_of_its_rows_is(self, service, logs):
        logs.list_since.return_value = [
            _log(
                2,
                ScheduleChangeAction.ASSIGN,
                at=_PUBLISHED + timedelta(seconds=1),
                new_space="Room B",
                moved_from_id=1,
            ),
            _log(1, ScheduleChangeAction.UNASSIGN, old_space="Room A", important=True),
        ]

        (erratum,) = service.list_for_event(_EVENT_PK)

        assert erratum.important

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


class TestSetImportant:
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
            service.set_important(event_pk=_EVENT_PK, log_pks=[2], important=True)

        logs.set_important.assert_not_called()
