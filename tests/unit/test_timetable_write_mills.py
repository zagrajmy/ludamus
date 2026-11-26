from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, call

import pytest

from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.sessions import SessionStatus
from ludamus.pacts.timetable import (
    PlacementRejectedError,
    PlacementRejection,
    ScheduleChangeAction,
    ScheduleChangeLogDTO,
    SessionPlacement,
)
from tests.unit.factories import agenda_item_dto, session_dto, space_dto
from tests.unit.timetable_helpers import (
    END,
    START,
    FakeAgendaItems,
    con_event,
    lookup,
    spec_uow,
    spheres_stub,
    timetable_service,
)

UNASSIGN_LOG_PK = 77


class _FakeScheduleChangeLogs:
    def __init__(self, *logs):
        self.rows = {log.pk: log for log in logs}
        self.created: list[dict] = []

    def create(self, data):
        self.created.append(data)
        return len(self.rows) + len(self.created)

    def read(self, pk):
        return self.rows[pk]

    def latest_pk_for_session(self, event_pk, session_id):
        return max(
            (
                log.pk
                for log in self.rows.values()
                if log.event_id == event_pk and log.session_id == session_id
            ),
            default=None,
        )


def _session(**overrides):
    return session_dto(
        **{"creation_time": START, "modification_time": START, **overrides}
    )


def _schedule_log(**overrides):
    defaults = {
        "pk": 1,
        "event_id": 1,
        "session_id": 1,
        "session_title": "Session",
        "user_id": None,
        "user_name": "",
        "action": ScheduleChangeAction.ASSIGN,
        "old_space_id": None,
        "old_space_name": None,
        "new_space_id": None,
        "new_space_name": None,
        "old_start_time": None,
        "old_end_time": None,
        "new_start_time": None,
        "new_end_time": None,
        "creation_time": START,
        "moved_from_id": None,
        "acknowledgement_time": None,
        "acknowledged_by_name": "",
        "important": False,
    }
    return ScheduleChangeLogDTO(**(defaults | overrides))


class TestAssignSession:
    @pytest.fixture
    def mock_uow(self):
        return MagicMock()

    @pytest.fixture
    def service(self, mock_uow):
        return timetable_service(mock_uow)

    @staticmethod
    def _event(pk, *, auto_confirm_sessions=True):
        event = MagicMock()
        event.pk = pk
        event.auto_confirm_sessions = auto_confirm_sessions
        return event

    @staticmethod
    def _placement(space_pk=1):
        return SessionPlacement(
            space_pk=space_pk,
            start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
        )

    def test_unassign_removes_the_row_and_returns_its_log(self, service, mock_uow):
        mock_uow.sessions.read_event.return_value = self._event(1)
        agenda_item = MagicMock()
        agenda_item.pk = 5
        agenda_item.space_id = 2
        agenda_item.start_time = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        agenda_item.end_time = datetime(2026, 1, 1, 11, 0, tzinfo=UTC)
        mock_uow.agenda_items.read_by_session.return_value = agenda_item
        mock_uow.schedule_change_logs.create.return_value = UNASSIGN_LOG_PK

        result = service.unassign_session(session_pk=4, event_pk=1, user_pk=9)

        assert result == UNASSIGN_LOG_PK
        mock_uow.sessions.lock.assert_called_once_with(4)
        mock_uow.agenda_items.delete.assert_called_once_with(5)
        mock_uow.schedule_change_logs.create.assert_called_once_with(
            {
                "event_id": 1,
                "session_id": 4,
                "user_id": 9,
                "action": ScheduleChangeAction.UNASSIGN,
                "old_space_id": 2,
                "old_start_time": agenda_item.start_time,
                "old_end_time": agenda_item.end_time,
            }
        )

    def test_unassign_raises_not_found_when_nothing_is_placed(self, service, mock_uow):
        mock_uow.sessions.read_event.return_value = self._event(1)
        mock_uow.agenda_items.read_by_session.return_value = None

        with pytest.raises(NotFoundError):
            service.unassign_session(session_pk=4, event_pk=1)

        mock_uow.agenda_items.delete.assert_not_called()
        mock_uow.schedule_change_logs.create.assert_not_called()

    def _arrange_acceptable_assignment(self, mock_uow, *, auto_confirm_sessions):
        placement = self._placement()
        event = self._event(1, auto_confirm_sessions=auto_confirm_sessions)
        event.start_time = placement.start_time - timedelta(days=1)
        event.end_time = placement.end_time + timedelta(days=1)
        event.publication_time = None
        mock_uow.sessions.read_event.return_value = event
        mock_uow.events.read.return_value = event
        space = MagicMock()
        space.pk = 1
        space.parent_id = None
        mock_uow.spaces.list_by_event.return_value = [space]
        mock_uow.agenda_items.read_by_session.return_value = None
        session = MagicMock()
        session.status = SessionStatus.ACCEPTED
        mock_uow.sessions.read.return_value = session

    def test_assign_without_a_space_is_refused_where_one_is_required(
        self, service, mock_uow
    ):
        self._arrange_acceptable_assignment(mock_uow, auto_confirm_sessions=True)
        mock_uow.sessions.read_event.return_value.require_session_space = True
        placement = replace(self._placement(), space_pk=None)

        with pytest.raises(PlacementRejectedError) as excinfo:
            service.assign_session(session_pk=1, placement=placement, event_pk=1)

        assert excinfo.value.reason is PlacementRejection.SPACE_REQUIRED
        mock_uow.agenda_items.create.assert_not_called()

    def test_assign_without_a_space_places_it_where_none_is_required(
        self, service, mock_uow
    ):
        self._arrange_acceptable_assignment(mock_uow, auto_confirm_sessions=True)
        mock_uow.sessions.read_event.return_value.require_session_space = False
        placement = replace(self._placement(), space_pk=None)

        service.assign_session(session_pk=1, placement=placement, event_pk=1)

        (created,) = mock_uow.agenda_items.create.call_args.args
        assert created["space_id"] is None
        mock_uow.spaces.lock.assert_not_called()

    def test_assign_is_a_noop_for_the_existing_placement(self, service, mock_uow):
        self._arrange_acceptable_assignment(mock_uow, auto_confirm_sessions=True)
        placement = self._placement()
        existing = MagicMock()
        existing.space_id = placement.space_pk
        existing.start_time = placement.start_time
        existing.end_time = placement.end_time
        mock_uow.agenda_items.read_by_session.return_value = existing

        service.assign_session(session_pk=1, placement=placement, event_pk=1)

        mock_uow.agenda_items.delete.assert_not_called()
        mock_uow.agenda_items.create.assert_not_called()
        mock_uow.schedule_change_logs.create.assert_not_called()

    def test_assign_treats_a_changed_end_as_a_move(self, service, mock_uow):
        self._arrange_acceptable_assignment(mock_uow, auto_confirm_sessions=True)
        placement = self._placement()
        existing = MagicMock()
        existing.pk = 11
        existing.space_id = placement.space_pk
        existing.start_time = placement.start_time
        existing.end_time = placement.end_time + timedelta(minutes=30)
        mock_uow.agenda_items.read_by_session.return_value = existing

        service.assign_session(session_pk=1, placement=placement, event_pk=1)

        mock_uow.agenda_items.delete.assert_called_once_with(11)
        mock_uow.agenda_items.create.assert_called_once()

    def test_assign_inside_the_event_leaves_its_dates_alone(self, service, mock_uow):
        self._arrange_acceptable_assignment(mock_uow, auto_confirm_sessions=True)

        service.assign_session(session_pk=1, placement=self._placement(), event_pk=1)

        mock_uow.events.update.assert_not_called()

    @pytest.mark.parametrize("naive_side", ("start_time", "end_time", "both"))
    def test_assign_rejects_naive_datetimes(self, service, mock_uow, naive_side):
        placement = self._placement()
        naive = SessionPlacement(
            space_pk=placement.space_pk,
            start_time=(
                placement.start_time.replace(tzinfo=None)
                if naive_side != "end_time"
                else placement.start_time
            ),
            end_time=(
                placement.end_time.replace(tzinfo=None)
                if naive_side != "start_time"
                else placement.end_time
            ),
        )

        with pytest.raises(PlacementRejectedError) as excinfo:
            service.assign_session(session_pk=1, placement=naive, event_pk=1)

        assert excinfo.value.reason is PlacementRejection.NAIVE_DATETIME
        assert str(excinfo.value) == "placement datetimes must include a timezone"
        mock_uow.atomic.assert_not_called()
        mock_uow.agenda_items.create.assert_not_called()

    @pytest.mark.parametrize("length", (timedelta(hours=-1), timedelta(0)))
    def test_assign_rejects_a_time_range_that_does_not_move_forward(
        self, service, mock_uow, length
    ):
        placement = self._placement()
        inverted = SessionPlacement(
            space_pk=placement.space_pk,
            start_time=placement.start_time,
            end_time=placement.start_time + length,
        )

        with pytest.raises(PlacementRejectedError) as excinfo:
            service.assign_session(session_pk=1, placement=inverted, event_pk=1)

        assert excinfo.value.reason is PlacementRejection.END_NOT_AFTER_START
        assert str(excinfo.value) == "end_time must be after start_time"
        mock_uow.atomic.assert_not_called()
        mock_uow.agenda_items.create.assert_not_called()

    def test_assign_writes_the_placement_and_its_log(self, service, mock_uow):
        self._arrange_acceptable_assignment(mock_uow, auto_confirm_sessions=True)
        placement = self._placement()

        service.assign_session(session_pk=4, placement=placement, event_pk=1, user_pk=9)

        mock_uow.sessions.lock.assert_called_once_with(4)
        mock_uow.spaces.lock.assert_called_once_with(1)
        mock_uow.agenda_items.delete.assert_not_called()
        mock_uow.agenda_items.create.assert_called_once_with(
            {
                "session_id": 4,
                "space_id": 1,
                "start_time": placement.start_time,
                "end_time": placement.end_time,
                "session_confirmed": True,
            }
        )
        mock_uow.schedule_change_logs.create.assert_called_once_with(
            {
                "event_id": 1,
                "session_id": 4,
                "user_id": 9,
                "action": ScheduleChangeAction.ASSIGN,
                "new_space_id": 1,
                "new_start_time": placement.start_time,
                "new_end_time": placement.end_time,
                "moved_from_id": None,
            }
        )

    def test_move_unconfirms_even_when_event_auto_confirms(self, service, mock_uow):
        self._arrange_acceptable_assignment(mock_uow, auto_confirm_sessions=True)
        mock_uow.agenda_items.read_by_session.return_value = MagicMock()

        service.assign_session(session_pk=1, placement=self._placement(), event_pk=1)

        created = mock_uow.agenda_items.create.call_args.args[0]
        assert created["session_confirmed"] is False
        # Once for the unassign the move rides on, once for the new slot.
        assert mock_uow.sessions.update.call_args_list == [
            call(1, {"schedule_confirmed": False}),
            call(1, {"schedule_confirmed": False}),
        ]

    def test_move_records_the_row_it_left(self, service, mock_uow):
        self._arrange_acceptable_assignment(mock_uow, auto_confirm_sessions=True)
        placement = self._placement()
        existing = MagicMock()
        existing.pk = 11
        existing.space_id = 2
        existing.start_time = placement.start_time - timedelta(hours=2)
        existing.end_time = placement.end_time - timedelta(hours=2)
        mock_uow.agenda_items.read_by_session.return_value = existing
        mock_uow.schedule_change_logs.create.return_value = UNASSIGN_LOG_PK

        service.assign_session(session_pk=4, placement=placement, event_pk=1, user_pk=9)

        mock_uow.agenda_items.delete.assert_called_once_with(11)
        assert mock_uow.schedule_change_logs.create.call_args_list == [
            call(
                {
                    "event_id": 1,
                    "session_id": 4,
                    "user_id": 9,
                    "action": ScheduleChangeAction.UNASSIGN,
                    "old_space_id": 2,
                    "old_start_time": existing.start_time,
                    "old_end_time": existing.end_time,
                }
            ),
            call(
                {
                    "event_id": 1,
                    "session_id": 4,
                    "user_id": 9,
                    "action": ScheduleChangeAction.ASSIGN,
                    "new_space_id": 1,
                    "new_start_time": placement.start_time,
                    "new_end_time": placement.end_time,
                    "moved_from_id": UNASSIGN_LOG_PK,
                }
            ),
        ]


class TestAssignSessionRejections:
    @staticmethod
    def _placement(space_pk=1, start=START, end=END):
        return SessionPlacement(space_pk=space_pk, start_time=start, end_time=end)

    @pytest.fixture
    def uow(self):
        uow = spec_uow(
            agenda_items=FakeAgendaItems(),
            schedule_change_logs=_FakeScheduleChangeLogs(),
        )
        uow.sessions.read.return_value = _session()
        uow.sessions.read_event.return_value = con_event()
        uow.events.read.return_value = con_event()
        uow.spaces.list_by_event.return_value = [space_dto(pk=1)]
        return uow

    def test_a_space_outside_the_event_is_not_found(self, uow):
        with pytest.raises(NotFoundError):
            timetable_service(uow).assign_session(
                session_pk=1, placement=self._placement(space_pk=2), event_pk=1
            )

        assert uow.agenda_items.created == []

    def test_a_drop_before_publication_is_rejected(self, uow):
        published = con_event(
            start_time=START + timedelta(days=1),
            publication_time=START + timedelta(hours=1),
        )
        uow.sessions.read_event.return_value = published
        uow.events.read.side_effect = lookup({1: published})

        with pytest.raises(PlacementRejectedError) as excinfo:
            timetable_service(uow).assign_session(
                session_pk=1, placement=self._placement(), event_pk=1
            )

        assert excinfo.value.reason is PlacementRejection.BEFORE_PUBLICATION
        assert str(excinfo.value) == (
            "start_time is before the event's publication_time; move the "
            "publication first (update_event)"
        )
        assert uow.agenda_items.created == []

    def test_an_accepted_drop_places_the_session_and_logs_it(self, uow):
        timetable_service(uow).assign_session(
            session_pk=1, placement=self._placement(), event_pk=1, user_pk=4
        )

        assert [item["session_id"] for item in uow.agenda_items.created] == [1]
        assert uow.schedule_change_logs.created == [
            {
                "event_id": 1,
                "session_id": 1,
                "user_id": 4,
                "action": ScheduleChangeAction.ASSIGN,
                "new_space_id": 1,
                "new_start_time": START,
                "new_end_time": END,
                "moved_from_id": None,
            }
        ]


class TestUnassignSession:
    def test_an_unscheduled_session_is_not_found(self):
        uow = spec_uow(
            agenda_items=FakeAgendaItems(),
            schedule_change_logs=_FakeScheduleChangeLogs(),
        )
        uow.sessions.read_event.return_value = con_event()

        with pytest.raises(NotFoundError):
            timetable_service(uow).unassign_session(session_pk=1, event_pk=1)

        assert uow.schedule_change_logs.created == []


class TestRevertChange:
    @pytest.fixture
    def mock_uow(self):
        uow = MagicMock()
        uow.schedule_change_logs.latest_pk_for_session.return_value = 1
        return uow

    @pytest.fixture
    def service(self, mock_uow):
        return timetable_service(mock_uow)

    def test_revert_unassign_raises_when_session_not_accepted(self, service, mock_uow):
        log = MagicMock()
        log.event_id = 1
        log.action = ScheduleChangeAction.UNASSIGN
        log.session_id = 1
        log.old_space_id = 5
        log.old_start_time = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        log.old_end_time = datetime(2026, 1, 1, 11, 0, tzinfo=UTC)
        mock_uow.schedule_change_logs.read.return_value = log

        session = MagicMock()
        session.status = SessionStatus.PENDING
        mock_uow.sessions.read.return_value = session

        with pytest.raises(PlacementRejectedError) as excinfo:
            service.revert_change(log_pk=1, event_pk=1)

        assert excinfo.value.reason is PlacementRejection.SESSION_NOT_ACCEPTED
        assert str(excinfo.value) == "Session 1 is not in ACCEPTED status"
        mock_uow.agenda_items.create.assert_not_called()

    def test_revert_assign_removes_the_placement_and_logs_where_it_was(
        self, service, mock_uow
    ):
        log = MagicMock()
        log.event_id = 1
        log.action = ScheduleChangeAction.ASSIGN
        log.session_id = 7
        log.new_space_id = 5
        log.new_start_time = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        log.new_end_time = datetime(2026, 1, 1, 11, 0, tzinfo=UTC)
        mock_uow.schedule_change_logs.read.return_value = log
        mock_uow.schedule_change_logs.latest_pk_for_session.return_value = 3
        mock_uow.agenda_items.read_by_session.return_value.pk = 11
        mock_uow.sessions.read_event.return_value.pk = 1

        service.revert_change(log_pk=3, event_pk=1, user_pk=9)

        mock_uow.agenda_items.delete.assert_called_once_with(11)
        mock_uow.agenda_items.create.assert_not_called()
        mock_uow.schedule_change_logs.create.assert_called_once_with(
            {
                "event_id": 1,
                "session_id": 7,
                "user_id": 9,
                "action": ScheduleChangeAction.REVERT,
                "old_space_id": 5,
                "old_start_time": log.new_start_time,
                "old_end_time": log.new_end_time,
            }
        )


class TestRevertChangeOutcomes:
    @pytest.fixture
    def uow(self):
        uow = spec_uow(
            agenda_items=FakeAgendaItems(),
            schedule_change_logs=_FakeScheduleChangeLogs(),
        )
        uow.sessions.read.side_effect = lookup({1: _session()})
        uow.sessions.read_event.side_effect = lookup({1: con_event()})
        return uow

    @staticmethod
    def _revert(uow, log_pk=1):
        timetable_service(uow).revert_change(log_pk=log_pk, event_pk=1, user_pk=4)

    def test_a_log_from_another_event_is_not_found(self, uow):
        uow.schedule_change_logs.rows = {1: _schedule_log(event_id=2)}

        with pytest.raises(NotFoundError):
            self._revert(uow)

    def test_only_the_latest_change_of_a_session_reverts(self, uow):
        uow.schedule_change_logs.rows = {
            1: _schedule_log(pk=1),
            2: _schedule_log(pk=2, action=ScheduleChangeAction.UNASSIGN),
        }

        with pytest.raises(
            ValueError, match=r"^Only the latest change for a session can be reverted$"
        ):
            self._revert(uow, log_pk=1)

        assert uow.schedule_change_logs.created == []

    def test_reverting_an_assign_takes_the_session_off_the_grid(self, uow):
        uow.agenda_items.rows = {7: agenda_item_dto(pk=7, session_id=1, space_id=3)}
        uow.schedule_change_logs.rows = {
            1: _schedule_log(new_space_id=3, new_start_time=START, new_end_time=END)
        }

        self._revert(uow)

        uow.sessions.lock.assert_called_once_with(1)
        uow.sessions.update.assert_called_once_with(1, {"schedule_confirmed": False})
        assert uow.agenda_items.rows == {}
        assert uow.schedule_change_logs.created == [
            {
                "event_id": 1,
                "session_id": 1,
                "user_id": 4,
                "action": ScheduleChangeAction.REVERT,
                "old_space_id": 3,
                "old_start_time": START,
                "old_end_time": END,
            }
        ]

    def test_reverting_an_assign_of_an_already_removed_item_is_not_found(self, uow):
        uow.schedule_change_logs.rows = {1: _schedule_log()}

        with pytest.raises(NotFoundError):
            self._revert(uow)

        assert uow.schedule_change_logs.created == []

    def test_reverting_an_unassign_puts_the_session_back(self, uow):
        uow.schedule_change_logs.rows = {
            1: _schedule_log(
                action=ScheduleChangeAction.UNASSIGN,
                old_space_id=3,
                old_start_time=START,
                old_end_time=END,
            )
        }

        self._revert(uow)

        uow.sessions.update.assert_called_once_with(1, {"schedule_confirmed": False})
        assert uow.agenda_items.created == [
            {
                "session_id": 1,
                "space_id": 3,
                "start_time": START,
                "end_time": END,
                "session_confirmed": False,
            }
        ]
        assert uow.schedule_change_logs.created == [
            {
                "event_id": 1,
                "session_id": 1,
                "user_id": 4,
                "action": ScheduleChangeAction.REVERT,
                "new_space_id": 3,
                "new_start_time": START,
                "new_end_time": END,
            }
        ]

    @pytest.mark.parametrize("missing", ("old_start_time", "old_end_time"))
    def test_an_unassign_missing_any_part_of_its_placement_cannot_revert(
        self, uow, missing
    ):
        placement = {"old_space_id": 3, "old_start_time": START, "old_end_time": END}
        uow.schedule_change_logs.rows = {
            1: _schedule_log(
                action=ScheduleChangeAction.UNASSIGN, **(placement | {missing: None})
            )
        }

        with pytest.raises(
            ValueError,
            match=r"^Cannot revert UNASSIGN: missing original placement data$",
        ):
            self._revert(uow)

        assert uow.agenda_items.created == []

    def test_an_unassign_without_a_space_cannot_revert_where_one_is_required(self, uow):
        uow.schedule_change_logs.rows = {
            1: _schedule_log(
                action=ScheduleChangeAction.UNASSIGN,
                old_space_id=None,
                old_start_time=START,
                old_end_time=END,
            )
        }

        with pytest.raises(ValueError, match="its space no longer exists"):
            self._revert(uow)

        assert uow.agenda_items.created == []

    def test_an_unassign_without_a_space_reverts_where_none_is_required(self, uow):
        uow.spheres = spheres_stub(require_session_space=False)
        uow.schedule_change_logs.rows = {
            1: _schedule_log(
                action=ScheduleChangeAction.UNASSIGN,
                old_space_id=None,
                old_start_time=START,
                old_end_time=END,
            )
        }

        self._revert(uow)

        assert [item["space_id"] for item in uow.agenda_items.created] == [None]

    def test_a_revert_row_itself_cannot_be_reverted(self, uow):
        uow.schedule_change_logs.rows = {
            1: _schedule_log(action=ScheduleChangeAction.REVERT)
        }

        with pytest.raises(ValueError, match="Cannot revert action"):
            self._revert(uow)

        assert uow.schedule_change_logs.created == []
