from contextlib import nullcontext
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest

from ludamus.mills.timetable import (
    ConflictDetectionService,
    TimetableOverviewService,
    TimetableService,
)
from ludamus.pacts import (
    AgendaItemDTO,
    AgendaItemRepositoryProtocol,
    EventRepositoryProtocol,
    NotFoundError,
    ScheduleChangeAction,
    ScheduleChangeLogDTO,
    ScheduleChangeLogRepositoryProtocol,
    SessionRepositoryProtocol,
    SessionStatus,
    SpaceDTO,
    SpaceRepositoryProtocol,
    TimeSlotDTO,
    TimeSlotRepositoryProtocol,
    TrackDTO,
    TrackRepositoryProtocol,
    TrackSessionCountsDTO,
)
from ludamus.pacts.chronology import (
    CapacityHoursDTO,
    ConflictDTO,
    ConflictSeverity,
    ConflictType,
    HeatmapCellDTO,
    HeatmapCellStatus,
    HeatmapDayDTO,
    HeatmapDTO,
    HeatmapRowDTO,
    SessionPlacement,
    SpaceGroupDTO,
    TimetableGridFilter,
    TrackProgressDTO,
)
from ludamus.pacts.timetable import (
    PlacementRejectedError,
    PlacementRejection,
    TimetableRepos,
)
from tests.unit.factories import event_dto, session_dto, track_dto

UNASSIGN_LOG_PK = 77


def _timetable_repos(uow) -> TimetableRepos:
    return TimetableRepos(
        events=uow.events,
        sessions=uow.sessions,
        agenda_items=uow.agenda_items,
        spaces=uow.spaces,
        time_slots=uow.time_slots,
        tracks=uow.tracks,
        schedule_change_logs=uow.schedule_change_logs,
    )


def _timetable_service(uow) -> TimetableService:
    transaction = MagicMock()
    transaction.atomic = uow.atomic
    return TimetableService(transaction, _timetable_repos(uow))


def _conflict_service(uow) -> ConflictDetectionService:
    return ConflictDetectionService(_timetable_repos(uow))


def _overview_service(uow) -> TimetableOverviewService:
    return TimetableOverviewService(_timetable_repos(uow))


def _make_item(**overrides):
    defaults = {
        "pk": 1,
        "session_id": 1,
        "session_title": "Session",
        "space_id": 1,
        "start_time": datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
        "end_time": datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
        "schedule_confirmed": False,
    }
    defaults.update(overrides)
    return AgendaItemDTO(**defaults)


class TestBuildGridOverlappingSessions:
    def test_overlapping_items_are_placed_side_by_side(self):
        uow = MagicMock()
        event = MagicMock()
        event.start_time = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        event.end_time = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        uow.events.read.return_value = event

        now = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        space = SpaceDTO(
            capacity=None,
            creation_time=now,
            modification_time=now,
            name="Room 1",
            order=0,
            pk=1,
            slug="room-1",
        )
        uow.spaces.list_by_event.return_value = [space]
        uow.time_slots.list_by_event.return_value = [
            TimeSlotDTO(
                pk=1,
                start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                end_time=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
            )
        ]

        item_a = _make_item(
            pk=1,
            space_id=1,
            start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
        )
        item_b = _make_item(
            pk=2,
            space_id=1,
            start_time=datetime(2026, 1, 1, 10, 30, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, 11, 30, tzinfo=UTC),
        )
        item_c = _make_item(
            pk=3,
            space_id=1,
            start_time=datetime(2026, 1, 1, 11, 30, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        )
        uow.agenda_items.list_by_event.return_value = [item_a, item_b, item_c]

        svc = _timetable_service(uow)
        grid = svc.build_grid(event_pk=1, tz=UTC)

        sessions = grid.days[0].columns[0].sessions
        expected_count = 3
        expected_half_width = 50.0
        assert len(sessions) == expected_count
        assert sessions[0].lane_width_pct == pytest.approx(expected_half_width)
        assert sessions[1].lane_width_pct == pytest.approx(expected_half_width)
        assert sessions[0].lane_start_pct == pytest.approx(0.0)
        assert sessions[1].lane_start_pct == pytest.approx(expected_half_width)

    def test_a_chain_of_overlaps_shares_one_group(self):
        uow = _spec_uow(
            agenda_items=_FakeAgendaItems(
                _make_item(
                    pk=1,
                    session_id=1,
                    start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                    end_time=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
                ),
                _make_item(
                    pk=2,
                    session_id=2,
                    start_time=datetime(2026, 1, 1, 10, 30, tzinfo=UTC),
                    end_time=datetime(2026, 1, 1, 11, 30, tzinfo=UTC),
                ),
                _make_item(
                    pk=3,
                    session_id=3,
                    start_time=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
                    end_time=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
                ),
            )
        )
        uow.spaces.list_by_event.side_effect = _lookup({1: [_space(1)]})
        uow.time_slots.list_by_event.side_effect = _lookup(
            {1: [_slot(_START, _START + timedelta(hours=2))]}
        )
        _stub_warning_reads(uow)

        grid = _timetable_service(uow).build_grid(event_pk=1, tz=UTC)

        sessions = grid.days[0].columns[0].sessions
        assert [pos.lane_width_pct for pos in sessions] == pytest.approx([100 / 3] * 3)
        assert [pos.lane_start_pct for pos in sessions] == pytest.approx(
            [0, 100 / 3, 200 / 3]
        )

    def test_a_booking_ending_as_the_day_opens_is_not_shown(self):
        uow = _spec_uow(
            agenda_items=_FakeAgendaItems(
                _make_item(
                    start_time=_START - timedelta(hours=1), end_time=_START, space_id=1
                )
            )
        )
        uow.spaces.list_by_event.side_effect = _lookup({1: [_space(1)]})
        uow.time_slots.list_by_event.side_effect = _lookup({1: [_slot(_START, _END)]})
        _stub_warning_reads(uow)

        grid = _timetable_service(uow).build_grid(event_pk=1, tz=UTC)

        assert grid.days[0].columns[0].sessions == []

    def test_all_days_share_rooms_and_one_time_axis(self):
        uow = MagicMock()
        now = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        space = SpaceDTO(
            capacity=None,
            creation_time=now,
            modification_time=now,
            name="Room 1",
            order=0,
            pk=1,
            slug="room-1",
        )
        uow.spaces.list_by_event.return_value = [space]
        uow.time_slots.list_by_event.return_value = [
            TimeSlotDTO(
                pk=2,
                start_time=datetime(2026, 1, 2, 11, 0, tzinfo=UTC),
                end_time=datetime(2026, 1, 2, 13, 0, tzinfo=UTC),
            ),
            TimeSlotDTO(
                pk=1,
                start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                end_time=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
            ),
        ]
        uow.agenda_items.list_by_event.return_value = [
            _make_item(
                pk=1,
                session_title="Day one",
                start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                end_time=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
            ),
            _make_item(
                pk=2,
                session_id=2,
                session_title="Day two",
                start_time=datetime(2026, 1, 2, 11, 0, tzinfo=UTC),
                end_time=datetime(2026, 1, 2, 12, 0, tzinfo=UTC),
            ),
        ]

        grid = _timetable_service(uow).build_grid(
            event_pk=1, tz=UTC, filters=TimetableGridFilter(date_selection="all")
        )

        assert [day.date.isoformat() for day in grid.days] == [
            "2026-01-01",
            "2026-01-02",
        ]
        assert [day.columns[0].space.pk for day in grid.days] == [space.pk, space.pk]
        assert [
            day.columns[0].sessions[0].agenda_item.session_title for day in grid.days
        ] == ["Day one", "Day two"]
        # 10:00-12:00 and 11:00-13:00 share one 10:00-13:00 axis, so 11:00 is
        assert [day.total_minutes for day in grid.days] == [3 * 60, 3 * 60]
        assert [
            [label.time.strftime("%H:%M") for label in day.time_labels]
            for day in grid.days
        ] == [["10:00", "11:00", "12:00", "13:00"]] * 2
        assert [day.columns[0].sessions[0].start_minutes for day in grid.days] == [
            0,
            60,
        ]
        assert grid.date_selection == "all"

    def test_track_filter_still_shows_every_booking_in_the_visible_rooms(self):
        uow = MagicMock()
        now = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        space = SpaceDTO(
            capacity=None,
            creation_time=now,
            modification_time=now,
            name="Room 1",
            order=0,
            pk=1,
            slug="room-1",
        )
        uow.spaces.list_by_event.return_value = [space]
        uow.tracks.list_space_pks.side_effect = _lookup({5: [1]})
        uow.time_slots.list_by_event.return_value = [
            TimeSlotDTO(
                pk=1,
                start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                end_time=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
            )
        ]
        mine = _make_item(
            pk=1,
            session_title="Mine",
            start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
        )
        theirs = _make_item(
            pk=2,
            session_id=2,
            session_title="Theirs",
            start_time=datetime(2026, 1, 1, 10, 30, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, 11, 30, tzinfo=UTC),
        )
        untracked = _make_item(
            pk=3,
            session_id=3,
            session_title="Untracked",
            start_time=datetime(2026, 1, 1, 11, 30, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        )
        uow.agenda_items.list_by_event.return_value = [mine, theirs, untracked]
        uow.agenda_items.list_by_track.return_value = [mine]
        uow.tracks.read.side_effect = _lookup({5: _event_track(event_pk=1)})
        _stub_warning_reads(uow)
        uow.sessions.read_preferred_time_slots_by_sessions.side_effect = _subset(
            {3: [_slot(_START + timedelta(days=1), _END + timedelta(days=1))]}
        )

        grid = _timetable_service(uow).build_grid(
            event_pk=1, tz=UTC, filters=TimetableGridFilter(track_pk=5)
        )

        sessions = grid.days[0].columns[0].sessions
        assert [(pos.agenda_item.session_title, pos.state) for pos in sessions] == [
            ("Mine", "conflict"),
            ("Theirs", "conflict"),
            ("Untracked", "normal"),
        ]
        assert [(c.subject_session_pk, c.session_pk) for c in grid.conflicts] == [
            (1, 2)
        ]

    def test_invalid_date_falls_back_to_first_overnight_slot_date(self):
        uow = MagicMock()
        now = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        space = SpaceDTO(
            capacity=None,
            creation_time=now,
            modification_time=now,
            name="Room 1",
            order=0,
            pk=1,
            slug="room-1",
        )
        uow.spaces.list_by_event.return_value = [space]
        uow.time_slots.list_by_event.return_value = [
            TimeSlotDTO(
                pk=1,
                start_time=datetime(2026, 1, 1, 22, 0, tzinfo=UTC),
                end_time=datetime(2026, 1, 2, 2, 0, tzinfo=UTC),
            )
        ]
        uow.agenda_items.list_by_event.return_value = []

        grid = _timetable_service(uow).build_grid(
            event_pk=1,
            tz=UTC,
            filters=TimetableGridFilter(date_selection=date(2027, 1, 1)),
        )

        assert grid.date_selection == date(2026, 1, 1)
        assert [day.total_minutes for day in grid.days] == [2 * 60]

    def test_overnight_slot_adds_the_day_it_reaches_into(self):
        uow = MagicMock()
        now = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        space = SpaceDTO(
            capacity=None,
            creation_time=now,
            modification_time=now,
            name="Room 1",
            order=0,
            pk=1,
            slug="room-1",
        )
        uow.spaces.list_by_event.return_value = [space]
        uow.time_slots.list_by_event.return_value = [
            TimeSlotDTO(
                pk=1,
                start_time=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
                end_time=datetime(2026, 1, 2, 1, 0, tzinfo=UTC),
            ),
            TimeSlotDTO(
                pk=2,
                start_time=datetime(2026, 1, 2, 12, 0, tzinfo=UTC),
                end_time=datetime(2026, 1, 2, 22, 0, tzinfo=UTC),
            ),
        ]
        night_owl = _make_item(
            start_time=datetime(2026, 1, 2, 0, 0, tzinfo=UTC),
            end_time=datetime(2026, 1, 2, 1, 0, tzinfo=UTC),
        )
        uow.agenda_items.list_by_event.return_value = [night_owl]

        grid = _timetable_service(uow).build_grid(
            event_pk=1, tz=UTC, filters=TimetableGridFilter(date_selection="all")
        )

        assert grid.available_dates == [date(2026, 1, 1), date(2026, 1, 2)]
        day_one, day_two = grid.days
        assert [day.total_minutes for day in grid.days] == [24 * 60, 24 * 60]
        assert day_one.time_labels[0].time.strftime("%H:%M") == "00:00"
        assert day_two.time_labels[0].time.strftime("%H:%M") == "00:00"
        assert day_one.columns[0].sessions == []
        assert [pos.start_minutes for pos in day_two.columns[0].sessions] == [0]

    def test_session_crossing_midnight_renders_clipped_on_both_days(self):
        uow = MagicMock()
        now = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        space = SpaceDTO(
            capacity=None,
            creation_time=now,
            modification_time=now,
            name="Room 1",
            order=0,
            pk=1,
            slug="room-1",
        )
        uow.spaces.list_by_event.return_value = [space]
        uow.time_slots.list_by_event.return_value = [
            TimeSlotDTO(
                pk=1,
                start_time=datetime(2026, 1, 1, 22, 0, tzinfo=UTC),
                end_time=datetime(2026, 1, 2, 2, 0, tzinfo=UTC),
            )
        ]
        night_owl = _make_item(
            start_time=datetime(2026, 1, 1, 22, 0, tzinfo=UTC),
            end_time=datetime(2026, 1, 2, 2, 0, tzinfo=UTC),
            session_duration_minutes=4 * 60,
        )
        uow.agenda_items.list_by_event.return_value = [night_owl]

        grid = _timetable_service(uow).build_grid(
            event_pk=1, tz=UTC, filters=TimetableGridFilter(date_selection="all")
        )

        day_one, day_two = grid.days
        # 22:00 -> 24:00 on one day and 00:00 -> 02:00 on the next share a
        # 00:00 -> 24:00 axis, so each fragment sits at its own clock hour.
        assert [day.total_minutes for day in grid.days] == [24 * 60, 24 * 60]
        friday, saturday = (
            day_one.columns[0].sessions[0],
            (day_two.columns[0].sessions[0]),
        )
        assert (friday.start_minutes, friday.duration_minutes) == (22 * 60, 2 * 60)
        assert (saturday.start_minutes, saturday.duration_minutes) == (0, 2 * 60)
        assert friday.agenda_item.session_duration_minutes == 4 * 60


class TestSpaceFilter:
    @staticmethod
    def _space(*, pk, name, parent_id=None):
        now = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        return SpaceDTO(
            capacity=None,
            creation_time=now,
            modification_time=now,
            name=name,
            order=0,
            programme_order=pk,
            parent_id=parent_id,
            pk=pk,
            slug=f"space-{pk}",
        )

    @pytest.fixture
    def uow(self):
        uow = MagicMock()
        uow.spaces.list_by_event.return_value = [
            self._space(pk=1, name="Building A"),
            self._space(pk=2, name="Floor 2", parent_id=1),
            self._space(pk=3, name="Room 201", parent_id=2),
            self._space(pk=4, name="Room 202", parent_id=2),
            self._space(pk=5, name="Building B"),
            self._space(pk=6, name="Room 1", parent_id=5),
        ]
        uow.time_slots.list_by_event.return_value = [
            TimeSlotDTO(
                pk=1,
                start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                end_time=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
            )
        ]
        uow.agenda_items.list_by_event.return_value = []
        return uow

    def test_grid_uses_programme_order_instead_of_tree_order(self, uow):
        by_pk = {space.pk: space for space in uow.spaces.list_by_event.return_value}
        by_pk[6].programme_order = 0
        by_pk[3].programme_order = 1
        by_pk[4].programme_order = 2

        grid = _timetable_service(uow).build_grid(event_pk=1, tz=UTC)

        assert [space.pk for space in grid.spaces] == [6, 3, 4]


class TestRevertChange:
    @pytest.fixture
    def mock_uow(self):
        uow = MagicMock()
        uow.schedule_change_logs.latest_pk_for_session.return_value = 1
        uow.time_slots.list_by_event.return_value = [
            TimeSlotDTO(
                pk=1,
                start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                end_time=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
            )
        ]
        return uow

    @pytest.fixture
    def service(self, mock_uow):
        return _timetable_service(mock_uow)

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

        mock_uow.agenda_items.read_by_session.assert_called_once_with(7)
        mock_uow.agenda_items.delete.assert_called_once_with(11)
        mock_uow.agenda_items.create.assert_not_called()
        mock_uow.sessions.read.assert_not_called()
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


class TestAssignSession:
    @pytest.fixture
    def mock_uow(self):
        return MagicMock()

    @pytest.fixture
    def service(self, mock_uow):
        return _timetable_service(mock_uow)

    @staticmethod
    def _event(pk):
        event = MagicMock()
        event.pk = pk
        event.auto_confirm_sessions = True
        return event

    @staticmethod
    def _placement():
        return SessionPlacement(
            space_pk=1,
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
        assert mock_uow.sessions.read_event.call_args_list == [call(4), call(4)]
        mock_uow.sessions.lock.assert_called_once_with(4)
        mock_uow.agenda_items.read_by_session.assert_called_once_with(4)
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

    def _arrange_acceptable_assignment(self, mock_uow):
        placement = self._placement()
        event = MagicMock()
        event.pk = 1
        event.auto_confirm_sessions = True
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
        mock_uow.time_slots.list_by_event.return_value = [
            _slot_from(1, placement.start_time, hours=1)
        ]
        session = MagicMock()
        session.status = SessionStatus.ACCEPTED
        mock_uow.sessions.read.return_value = session

    def test_assign_is_a_noop_for_the_existing_placement(self, service, mock_uow):
        self._arrange_acceptable_assignment(mock_uow)
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
        self._arrange_acceptable_assignment(mock_uow)
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

    def test_assign_starting_before_a_slot_stretches_it_back(self, service, mock_uow):
        self._arrange_acceptable_assignment(mock_uow)
        placement = self._placement()
        later = _slot_from(1, placement.start_time + timedelta(minutes=30), hours=1)
        mock_uow.time_slots.list_by_event.return_value = [later]

        service.assign_session(session_pk=1, placement=placement, event_pk=1)

        mock_uow.time_slots.update.assert_called_once_with(
            1, placement.start_time, later.end_time
        )
        mock_uow.time_slots.create.assert_not_called()

    def test_assign_ending_where_a_slot_starts_stretches_it_back(
        self, service, mock_uow
    ):
        self._arrange_acceptable_assignment(mock_uow)
        placement = self._placement()
        after = _slot_from(1, placement.end_time, hours=1)
        mock_uow.time_slots.list_by_event.return_value = [after]

        service.assign_session(session_pk=1, placement=placement, event_pk=1)

        mock_uow.time_slots.update.assert_called_once_with(
            1, placement.start_time, after.end_time
        )
        mock_uow.time_slots.create.assert_not_called()

    def test_assign_touching_a_slot_stretches_it_to_the_placement(
        self, service, mock_uow
    ):
        self._arrange_acceptable_assignment(mock_uow)
        placement = self._placement()
        before = _slot_from(1, placement.start_time - timedelta(hours=1), hours=1)
        mock_uow.time_slots.list_by_event.return_value = [before]

        service.assign_session(session_pk=1, placement=placement, event_pk=1)

        mock_uow.time_slots.update.assert_called_once_with(
            1, before.start_time, placement.end_time
        )
        mock_uow.time_slots.create.assert_not_called()

    def test_assign_across_a_gap_closes_it(self, service, mock_uow):
        self._arrange_acceptable_assignment(mock_uow)
        placement = self._placement()
        before = _slot_from(1, placement.start_time - timedelta(minutes=30), hours=0.75)
        after = _slot_from(2, placement.start_time + timedelta(minutes=45), hours=1)
        mock_uow.time_slots.list_by_event.return_value = [before, after]

        service.assign_session(session_pk=1, placement=placement, event_pk=1)

        mock_uow.time_slots.update.assert_called_once_with(
            1, before.start_time, after.start_time
        )

    def test_assign_across_two_gaps_closes_each_to_its_neighbour(
        self, service, mock_uow
    ):
        self._arrange_acceptable_assignment(mock_uow)
        placement = self._placement()
        before = _slot_from(1, placement.start_time - timedelta(minutes=30), hours=0.5)
        middle = _slot_from(2, placement.start_time + timedelta(minutes=10), hours=0.25)
        after = _slot_from(3, placement.start_time + timedelta(minutes=40), hours=1)
        mock_uow.time_slots.list_by_event.return_value = [before, after, middle]

        service.assign_session(session_pk=1, placement=placement, event_pk=1)

        assert mock_uow.time_slots.update.call_args_list == [
            call(1, before.start_time, middle.start_time),
            call(2, middle.start_time, after.start_time),
        ]

    def test_assign_accepts_a_placement_across_adjacent_time_slots(
        self, service, mock_uow
    ):
        self._arrange_acceptable_assignment(mock_uow)
        placement = self._placement()
        first = MagicMock()
        first.start_time = placement.start_time
        first.end_time = placement.start_time + timedelta(minutes=30)
        second = MagicMock()
        second.start_time = first.end_time
        second.end_time = placement.end_time
        mock_uow.time_slots.list_by_event.return_value = [first, second]

        service.assign_session(session_pk=1, placement=placement, event_pk=1)

        mock_uow.agenda_items.create.assert_called_once()

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
        self._arrange_acceptable_assignment(mock_uow)
        placement = self._placement()

        service.assign_session(session_pk=4, placement=placement, event_pk=1, user_pk=9)

        assert mock_uow.sessions.read_event.call_args_list == [call(4), call(4)]
        mock_uow.sessions.lock.assert_called_once_with(4)
        mock_uow.spaces.list_by_event.assert_called_once_with(1)
        mock_uow.spaces.lock.assert_called_once_with(1)
        mock_uow.agenda_items.read_by_session.assert_called_once_with(4)
        mock_uow.sessions.read.assert_called_once_with(4)
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
        self._arrange_acceptable_assignment(mock_uow)
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
        self._arrange_acceptable_assignment(mock_uow)
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


def _facilitator(pk, display_name="Alice", *, is_collective=False):
    facilitator = MagicMock()
    facilitator.pk = pk
    facilitator.display_name = display_name
    facilitator.is_collective = is_collective
    return facilitator


def _slot_from(pk, start, *, hours):
    return TimeSlotDTO(pk=pk, start_time=start, end_time=start + timedelta(hours=hours))


def _event_track(*, event_pk):
    track = MagicMock()
    track.event_id = event_pk
    return track


_SUBJECT_SESSION_PK = 10
_OTHER_SESSION_PK = 20
_ROOM_CAPACITY = 10
_SESSION_LIMIT = 25


class TestListAllForTrack:
    @staticmethod
    def _uow(*, all_items, spaces=(), limits=None, facilitators=None):
        uow = MagicMock()
        uow.agenda_items.list_by_event.return_value = all_items
        uow.agenda_items.list_by_track.return_value = all_items
        uow.spaces.list_by_event.return_value = list(spaces)
        uow.sessions.read_participants_limits.side_effect = _subset(
            limits if limits is not None else {i.session_id: 0 for i in all_items}
        )
        uow.sessions.read_facilitators_by_sessions.return_value = facilitators or {}
        uow.sessions.list_track_names_by_session.return_value = {}
        uow.tracks.read.return_value = _event_track(event_pk=1)
        uow.tracks.list_manager_names_by_tracks.return_value = {}
        return uow

    def test_space_overlap_detected_and_deduplicated(self):
        first = _make_item(pk=1, session_id=10, space_id=1, session_title="First")
        second = _make_item(pk=2, session_id=20, space_id=1, session_title="Second")
        uow = self._uow(all_items=[first, second])

        conflicts = _conflict_service(uow).list_all_for_track(event_pk=1, track_pk=None)

        assert len(conflicts) == 1
        assert conflicts[0].type == ConflictType.SPACE_OVERLAP
        assert conflicts[0].subject_session_pk == _SUBJECT_SESSION_PK
        assert conflicts[0].session_pk == _OTHER_SESSION_PK

    def test_disjoint_times_in_same_space_do_not_conflict(self):
        first = _make_item(pk=1, session_id=10, space_id=1)
        second = _make_item(
            pk=2,
            session_id=20,
            space_id=1,
            start_time=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        )
        uow = self._uow(all_items=[first, second])

        conflicts = _conflict_service(uow).list_all_for_track(event_pk=1, track_pk=None)

        assert not conflicts

    def test_capacity_exceeded_uses_batched_limits(self):
        now = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        space = SpaceDTO(
            capacity=_ROOM_CAPACITY,
            creation_time=now,
            modification_time=now,
            name="Room 1",
            order=0,
            pk=1,
            slug="room-1",
        )
        item = _make_item(pk=1, session_id=10, space_id=1)
        uow = self._uow(all_items=[item], spaces=[space], limits={10: _SESSION_LIMIT})

        conflicts = _conflict_service(uow).list_all_for_track(event_pk=1, track_pk=None)

        assert len(conflicts) == 1
        assert conflicts[0].type == ConflictType.CAPACITY_EXCEEDED
        assert conflicts[0].space_capacity == _ROOM_CAPACITY
        assert conflicts[0].session_limit == _SESSION_LIMIT

    def test_a_room_as_big_as_the_limit_is_not_exceeded(self):
        item = _make_item(pk=1, session_id=10, space_id=1)
        uow = self._uow(
            all_items=[item],
            spaces=[_space(1, capacity=_SESSION_LIMIT)],
            limits={10: _SESSION_LIMIT},
        )

        conflicts = _conflict_service(uow).list_all_for_track(event_pk=1, track_pk=None)

        assert not conflicts

    def test_a_session_without_a_limit_fits_a_room_of_no_capacity(self):
        item = _make_item(pk=1, session_id=10, space_id=1)
        uow = self._uow(all_items=[item], spaces=[_space(1, capacity=0)], limits={})

        conflicts = _conflict_service(uow).list_all_for_track(event_pk=1, track_pk=None)

        assert not conflicts

    def test_collective_facilitator_overlap_is_not_a_conflict(self):
        subject = _make_item(pk=1, session_id=10, space_id=1)
        other = _make_item(pk=2, session_id=20, space_id=2, session_title="Other")
        shared = _facilitator(7, is_collective=True)
        uow = self._uow(
            all_items=[subject, other], facilitators={10: [shared], 20: [shared]}
        )

        conflicts = ConflictDetectionService(uow).list_all_for_track(
            event_pk=1, track_pk=None
        )

        assert not conflicts

    def test_collective_facilitator_still_clashes_over_a_space(self):
        subject = _make_item(pk=1, session_id=10, space_id=1)
        other = _make_item(pk=2, session_id=20, space_id=1, session_title="Other")
        shared = _facilitator(7, is_collective=True)
        uow = self._uow(
            all_items=[subject, other], facilitators={10: [shared], 20: [shared]}
        )

        conflicts = ConflictDetectionService(uow).list_all_for_track(
            event_pk=1, track_pk=None
        )

        assert [c.type for c in conflicts] == [ConflictType.SPACE_OVERLAP]

    def test_every_shared_facilitator_is_named_once(self):
        subject = _make_item(pk=1, session_id=10, space_id=1)
        other = _make_item(pk=2, session_id=20, space_id=2, session_title="Other")
        alice = _facilitator(7, display_name="Alice")
        bob = _facilitator(8, display_name="Bob")
        uow = self._uow(
            all_items=[subject, other],
            facilitators={10: [alice, bob], 20: [alice, bob]},
        )

        conflicts = _conflict_service(uow).list_all_for_track(event_pk=1, track_pk=None)

        assert [c.facilitator_name for c in conflicts] == ["Alice", "Bob"]

    def test_namesakes_shared_by_a_pair_are_two_clashes(self):
        subject = _make_item(pk=1, session_id=10, space_id=1)
        other = _make_item(pk=2, session_id=20, space_id=2, session_title="Other")
        first = _facilitator(7, display_name="Alice")
        second = _facilitator(8, display_name="Alice")
        uow = self._uow(
            all_items=[subject, other],
            facilitators={10: [first, second], 20: [first, second]},
        )

        conflicts = _conflict_service(uow).list_all_for_track(event_pk=1, track_pk=None)

        assert [c.facilitator_name for c in conflicts] == ["Alice", "Alice"]


class TestBuildHeatmap:
    @pytest.fixture
    def mock_uow(self):
        uow = MagicMock()
        event = MagicMock()
        event.start_time = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        event.end_time = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        uow.events.read.return_value = event
        uow.spaces.list_by_event.return_value = []
        uow.agenda_items.list_by_event.return_value = []
        uow.time_slots.list_by_event.return_value = []
        return uow

    @pytest.mark.parametrize(
        ("slot_end", "row_times"),
        (
            (datetime(2026, 1, 1, 11, 0, tzinfo=UTC), [10]),
            (datetime(2026, 1, 1, 11, 0, 30, tzinfo=UTC), [10, 11]),
            (datetime(2026, 1, 1, 11, 0, 0, 500_000, tzinfo=UTC), [10, 11]),
            (datetime(2026, 1, 1, 11, 30, tzinfo=UTC), [10, 11]),
            (datetime(2026, 1, 1, 12, 30, tzinfo=UTC), [10, 11, 12]),
        ),
    )
    def test_build_heatmap_rounds_the_day_out_to_whole_slots(
        self, mock_uow, slot_end, row_times
    ):
        mock_uow.spaces.list_by_event.return_value = [_space(3)]
        mock_uow.time_slots.list_by_event.return_value = [
            _slot(datetime(2026, 1, 1, 10, 0, tzinfo=UTC), slot_end)
        ]
        mock_uow.agenda_items.list_by_event.return_value = [
            _make_item(
                space_id=3,
                start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                end_time=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
            )
        ]

        result = TimetableOverviewService(mock_uow).build_heatmap(
            event_pk=1, tz=UTC, conflicts=[]
        )

        rows = [
            HeatmapRowDTO(
                time=datetime(2026, 1, 1, hour, 0, tzinfo=UTC),
                cells=[
                    HeatmapCellDTO(
                        space_pk=3,
                        status=(
                            HeatmapCellStatus.SCHEDULED
                            if hour == row_times[0]
                            else HeatmapCellStatus.EMPTY
                        ),
                    )
                ],
            )
            for hour in row_times
        ]
        assert result == HeatmapDTO(
            spaces=[_space(3)],
            rows=rows,
            days=[HeatmapDayDTO(date=date(2026, 1, 1), rows=rows)],
        )

    def test_build_heatmap_rounds_the_day_start_down_to_the_hour(self, mock_uow):
        mock_uow.spaces.list_by_event.return_value = [_space(3)]
        mock_uow.time_slots.list_by_event.return_value = [
            _slot(
                datetime(2026, 1, 1, 10, 30, 30, 500_000, tzinfo=UTC),
                datetime(2026, 1, 1, 11, 30, tzinfo=UTC),
            )
        ]

        result = TimetableOverviewService(mock_uow).build_heatmap(
            event_pk=1, tz=UTC, conflicts=[]
        )

        assert [row.time for row in result.rows] == [
            datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
            datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
        ]

    def test_build_heatmap_columns_are_leaf_spaces_only(self, mock_uow):
        mock_uow.spaces.list_by_event.return_value = [
            _space(1),
            _space(2, parent_id=1),
            _space(3, parent_id=2),
            _space(4, parent_id=2),
        ]
        mock_uow.time_slots.list_by_event.return_value = [
            _slot(
                datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
            )
        ]
        mock_uow.agenda_items.list_by_event.return_value = [_make_item(space_id=3)]
        svc = TimetableOverviewService(mock_uow)

        result = svc.build_heatmap(event_pk=1, tz=UTC, conflicts=[])

        assert [s.pk for s in result.spaces] == [3, 4]
        assert [c.space_pk for c in result.rows[0].cells] == [3, 4]
        assert [c.status for c in result.rows[0].cells] == [
            HeatmapCellStatus.SCHEDULED,
            HeatmapCellStatus.EMPTY,
        ]

    def test_build_heatmap_marks_both_ends_of_a_clash(self, mock_uow):
        mock_uow.spaces.list_by_event.return_value = [_space(3), _space(4)]
        mock_uow.time_slots.list_by_event.return_value = [
            _slot(
                datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
            )
        ]
        mock_uow.agenda_items.list_by_event.return_value = [
            _make_item(pk=1, session_id=10, space_id=3),
            _make_item(pk=2, session_id=20, space_id=4),
        ]
        conflict = ConflictDTO(
            type=ConflictType.FACILITATOR_OVERLAP,
            severity=ConflictSeverity.ERROR,
            subject_session_title="Mine",
            subject_session_pk=10,
            session_title="Theirs",
            session_pk=20,
        )

        result = TimetableOverviewService(mock_uow).build_heatmap(
            event_pk=1, tz=UTC, conflicts=[conflict]
        )

        assert [c.status for c in result.rows[0].cells] == [
            HeatmapCellStatus.CONFLICT,
            HeatmapCellStatus.CONFLICT,
        ]

    def test_all_conflicts_grouped_keeps_every_conflict_under_its_type(self):
        def conflict(kind, subject):
            return ConflictDTO(
                type=kind,
                severity=ConflictSeverity.ERROR,
                subject_session_title="Mine",
                subject_session_pk=subject,
                session_title="Theirs",
                session_pk=20,
            )

        first = conflict(ConflictType.FACILITATOR_OVERLAP, 10)
        second = conflict(ConflictType.FACILITATOR_OVERLAP, 11)
        other = conflict(ConflictType.SPACE_OVERLAP, 12)

        result = TimetableOverviewService(MagicMock()).all_conflicts_grouped(
            event_pk=1, conflicts=[first, other, second]
        )

        assert result == {
            ConflictType.FACILITATOR_OVERLAP: [first, second],
            ConflictType.SPACE_OVERLAP: [other],
        }


def _space(pk, parent_id=None, capacity=None):
    return SpaceDTO(
        pk=pk,
        parent_id=parent_id,
        capacity=capacity,
        creation_time=datetime(2026, 1, 1, tzinfo=UTC),
        modification_time=datetime(2026, 1, 1, tzinfo=UTC),
        name=f"Room {pk}",
        order=pk,
        slug=f"room-{pk}",
    )


def _slot(start, end):
    return TimeSlotDTO(pk=1, start_time=start, end_time=end)


class TestTimetableOverviewCapacityHours:
    @staticmethod
    def _uow(*, spaces, slots, items):
        uow = MagicMock()
        uow.spaces.list_by_event.return_value = spaces
        uow.time_slots.list_by_event.return_value = slots
        uow.agenda_items.list_by_event.return_value = items
        return uow

    def test_reads_rooms_slots_and_items_of_the_event(self):
        uow = self._uow(spaces=[], slots=[], items=[])

        _overview_service(uow).capacity_hours(event_pk=1)

        uow.spaces.list_by_event.assert_called_once_with(1)
        uow.time_slots.list_by_event.assert_called_once_with(1)
        uow.agenda_items.list_by_event.assert_called_once_with(1)

    def test_hours_are_rounded_to_one_decimal(self):
        uow = self._uow(
            spaces=[_space(1), _space(2)],
            slots=[
                _slot(
                    datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                    datetime(2026, 1, 1, 10, 20, tzinfo=UTC),
                )
            ],
            items=[
                _make_item(
                    space_id=1,
                    start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                    end_time=datetime(2026, 1, 1, 10, 10, tzinfo=UTC),
                )
            ],
        )

        result = _overview_service(uow).capacity_hours(event_pk=1)

        assert result == CapacityHoursDTO(
            room_count=2,
            slot_hours=0.3,
            capacity_hours=0.7,
            scheduled_hours=0.2,
            hours_to_fill=0.5,
            filled_pct=25,
        )

    def test_hours_count_every_second(self):
        uow = self._uow(
            spaces=[_space(1)],
            slots=[_slot(_START, _START + timedelta(hours=2, minutes=3, seconds=1))],
            items=[],
        )

        result = _overview_service(uow).capacity_hours(event_pk=1)

        assert result == CapacityHoursDTO(
            room_count=1,
            slot_hours=2.1,
            capacity_hours=2.1,
            scheduled_hours=0.0,
            hours_to_fill=2.1,
            filled_pct=0,
        )

    def test_empty_event_has_zero_everywhere(self):
        uow = self._uow(spaces=[], slots=[], items=[])

        result = _overview_service(uow).capacity_hours(event_pk=1)

        assert result == CapacityHoursDTO(
            room_count=0,
            slot_hours=0.0,
            capacity_hours=0.0,
            scheduled_hours=0.0,
            hours_to_fill=0.0,
            filled_pct=0,
        )

    def test_branch_spaces_are_not_bookable_rooms(self):
        slots = [
            _slot(
                datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
            )
        ]
        spaces = [_space(1), _space(2, parent_id=1), _space(3, parent_id=1)]
        uow = self._uow(spaces=spaces, slots=slots, items=[])

        result = _overview_service(uow).capacity_hours(event_pk=1)

        assert result == CapacityHoursDTO(
            room_count=2,
            slot_hours=2.0,
            capacity_hours=4.0,
            scheduled_hours=0.0,
            hours_to_fill=4.0,
            filled_pct=0,
        )

    def test_overbooked_clamps_hours_to_fill_to_zero(self):
        slots = [
            _slot(
                datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
            )
        ]
        items = [
            _make_item(
                space_id=1,
                start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                end_time=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
            )
        ]
        uow = self._uow(spaces=[_space(1)], slots=slots, items=items)

        result = _overview_service(uow).capacity_hours(event_pk=1)

        assert result == CapacityHoursDTO(
            room_count=1,
            slot_hours=1.0,
            capacity_hours=1.0,
            scheduled_hours=2.0,
            hours_to_fill=0.0,
            filled_pct=200,
        )


def _lookup(mapping):
    return mapping.__getitem__


def _subset(mapping):
    return lambda pks: {pk: mapping[pk] for pk in mapping.keys() & pks}


def _stub_warning_reads(uow):
    uow.sessions.read_facilitators_by_sessions.side_effect = _subset({})
    uow.sessions.read_participants_limits.side_effect = _subset({})
    uow.sessions.read_preferred_time_slots_by_sessions.side_effect = _subset({})
    uow.sessions.list_track_names_by_session.side_effect = _subset({})
    uow.tracks.list_manager_names_by_tracks.side_effect = _subset({})


def _spec_uow(**repos):
    uow = SimpleNamespace(
        atomic=nullcontext,
        events=MagicMock(spec=EventRepositoryProtocol),
        sessions=MagicMock(spec=SessionRepositoryProtocol),
        agenda_items=MagicMock(spec=AgendaItemRepositoryProtocol),
        spaces=MagicMock(spec=SpaceRepositoryProtocol),
        time_slots=MagicMock(spec=TimeSlotRepositoryProtocol),
        tracks=MagicMock(spec=TrackRepositoryProtocol),
        schedule_change_logs=MagicMock(spec=ScheduleChangeLogRepositoryProtocol),
    )
    uow.__dict__.update(repos)
    return uow


class _FakeAgendaItems:
    def __init__(self, *items):
        self.rows = {item.pk: item for item in items}
        self.event_pk = 1
        self.by_track: dict[int, list[AgendaItemDTO]] = {}
        self.facilitators_by_session: dict[int, set[int]] = {}
        self.created: list[dict] = []
        self.reads: list[tuple[int, set[int] | None]] = []

    def list_by_event(self, event_pk, facilitator_pks=None):
        self.reads.append((event_pk, facilitator_pks))
        return [
            item
            for item in self.rows.values()
            if event_pk == self.event_pk
            and (
                not facilitator_pks
                or self.facilitators_by_session.get(item.session_id, set())
                & facilitator_pks
            )
        ]

    def list_by_track(self, track_pk):
        return list(self.by_track.get(track_pk, []))

    def read_by_session(self, session_pk):
        return next(
            (item for item in self.rows.values() if item.session_id == session_pk), None
        )

    def create(self, data):
        self.created.append(data)

    def delete(self, pk):
        del self.rows[pk]


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


class _FakeTimeSlots:
    def __init__(self, *slots):
        self.rows = list(slots)
        self.event_pk = 1
        self.created: list[tuple] = []

    def list_by_event(self, event_id):
        return [slot for slot in self.rows if event_id == self.event_pk]

    def create(self, event_id, start_time, end_time):
        self.created.append((event_id, start_time, end_time))


_START = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
_END = datetime(2026, 1, 1, 11, 0, tzinfo=UTC)


def _event(**overrides):
    return event_dto(
        **{
            "end_time": _END + timedelta(days=1),
            "name": "Con",
            "slug": "con",
            "sphere_id": 3,
            "start_time": _START - timedelta(days=1),
            **overrides,
        }
    )


def _session(**overrides):
    return session_dto(
        **{"creation_time": _START, "modification_time": _START, **overrides}
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
        "creation_time": _START,
        "moved_from_id": None,
        "acknowledgement_time": None,
        "acknowledged_by_name": "",
        "important": False,
    }
    return ScheduleChangeLogDTO(**(defaults | overrides))


def _track(pk, name="Track"):
    return track_dto(
        creation_time=_START,
        modification_time=_START,
        name=name,
        pk=pk,
        slug=f"track-{pk}",
    )


class TestSpaceTree:
    @pytest.fixture
    def uow(self):
        uow = _spec_uow(agenda_items=_FakeAgendaItems())
        uow.spaces.list_by_event.side_effect = _lookup(
            {
                1: [
                    _space(1),
                    _space(2, parent_id=1),
                    _space(3, parent_id=2),
                    _space(4, parent_id=2),
                    _space(5),
                ]
            }
        )
        uow.time_slots.list_by_event.side_effect = _lookup({1: [_slot(_START, _END)]})
        _stub_warning_reads(uow)
        return uow

    def test_filter_options_follow_the_tree_with_depths(self, uow):
        options = _timetable_service(uow).space_filter_options(event_pk=1)

        assert [(o.value, o.depth) for o in options] == [
            (1, 0),
            (2, 1),
            (3, 2),
            (4, 2),
            (5, 0),
        ]

    def test_the_tree_is_read_once_per_service(self, uow):
        tree = uow.spaces.list_by_event(1)
        uow.spaces.list_by_event.side_effect = [tree, []]
        service = _timetable_service(uow)

        service.space_filter_options(event_pk=1)
        grid = service.build_grid(event_pk=1, tz=UTC)

        assert [space.pk for space in grid.spaces] == [3, 4, 5]

    def test_an_unfiltered_grid_reads_the_agenda_once(self, uow):
        _timetable_service(uow).build_grid(event_pk=1, tz=UTC)

        assert uow.agenda_items.reads == [(1, None)]

    def test_leaf_columns_group_under_their_parent(self, uow):
        grid = _timetable_service(uow).build_grid(event_pk=1, tz=UTC)

        assert grid.groups == [
            SpaceGroupDTO(parent_pk=2, parent_name="Room 2", span=2),
            SpaceGroupDTO(parent_pk=None, parent_name="", span=1),
        ]
        assert (grid.page, grid.total_pages, grid.total_spaces) == (1, 1, 3)

    def test_rooms_are_paged_five_at_a_time_from_the_first(self, uow):
        uow.spaces.list_by_event.side_effect = _lookup(
            {1: [_space(pk) for pk in range(1, 8)]}
        )
        service = _timetable_service(uow)

        first = service.build_grid(event_pk=1, tz=UTC)
        second = service.build_grid(event_pk=1, tz=UTC, space_page=2)

        assert [
            (
                grid.page,
                grid.total_pages,
                grid.total_spaces,
                grid.first_space_number,
                grid.last_space_number,
                [space.pk for space in grid.spaces],
            )
            for grid in (first, second)
        ] == [(1, 2, 7, 1, 5, [1, 2, 3, 4, 5]), (2, 2, 7, 6, 7, [6, 7])]

    def test_a_booking_renders_in_its_rooms_column(self, uow):
        uow.agenda_items.rows = {1: _make_item(space_id=4)}

        grid = _timetable_service(uow).build_grid(event_pk=1, tz=UTC)

        assert [
            [pos.agenda_item.session_title for pos in column.sessions]
            for column in grid.days[0].columns
        ] == [[], ["Session"], []]

    def test_the_facilitator_filter_narrows_the_shown_sessions(self, uow):
        uow.agenda_items.rows = {
            1: _make_item(pk=1, session_id=1, space_id=3, session_title="Mine"),
            2: _make_item(pk=2, session_id=2, space_id=4, session_title="Theirs"),
        }
        uow.agenda_items.facilitators_by_session = {1: {7}, 2: {8}}

        grid = _timetable_service(uow).build_grid(
            event_pk=1, tz=UTC, filters=TimetableGridFilter(facilitator_pks={7})
        )

        assert [
            [pos.agenda_item.session_title for pos in column.sessions]
            for column in grid.days[0].columns
        ] == [["Mine"], [], []]

    def test_selecting_a_branch_keeps_every_leaf_beneath_it(self, uow):
        grid = _timetable_service(uow).build_grid(
            event_pk=1, tz=UTC, filters=TimetableGridFilter(space_pks={2})
        )

        assert [space.pk for space in grid.spaces] == [3, 4]

    def test_a_foreign_space_pk_narrows_to_nothing(self, uow):
        grid = _timetable_service(uow).build_grid(
            event_pk=1, tz=UTC, filters=TimetableGridFilter(space_pks={99})
        )

        assert grid.spaces == []
        assert grid.total_pages == 1

    def test_without_time_slots_there_are_no_days(self, uow):
        uow.time_slots.list_by_event.side_effect = _lookup({1: []})

        grid = _timetable_service(uow).build_grid(
            event_pk=1,
            tz=UTC,
            filters=TimetableGridFilter(date_selection=_START.date()),
        )

        assert grid.days == []
        assert grid.total_columns == 0
        assert grid.date_selection == "all"


class TestAssignSessionRejections:
    @staticmethod
    def _placement(space_pk=1, start=_START, end=_END):
        return SessionPlacement(space_pk=space_pk, start_time=start, end_time=end)

    @pytest.fixture
    def uow(self):
        uow = _spec_uow(
            agenda_items=_FakeAgendaItems(),
            schedule_change_logs=_FakeScheduleChangeLogs(),
            time_slots=_FakeTimeSlots(),
        )
        uow.sessions.read.return_value = _session()
        uow.sessions.read_event.return_value = _event()
        uow.events.read.return_value = _event()
        uow.spaces.list_by_event.return_value = [_space(1)]
        return uow

    def test_a_space_outside_the_event_is_not_found(self, uow):
        with pytest.raises(NotFoundError):
            _timetable_service(uow).assign_session(
                session_pk=1, placement=self._placement(space_pk=2), event_pk=1
            )

        assert uow.agenda_items.created == []

    def test_a_drop_before_publication_is_rejected(self, uow):
        published = _event(
            start_time=_START + timedelta(days=1),
            publication_time=_START + timedelta(hours=1),
        )
        uow.sessions.read_event.return_value = published
        uow.events.read.side_effect = _lookup({1: published})

        with pytest.raises(PlacementRejectedError) as excinfo:
            _timetable_service(uow).assign_session(
                session_pk=1, placement=self._placement(), event_pk=1
            )

        assert excinfo.value.reason is PlacementRejection.BEFORE_PUBLICATION
        assert str(excinfo.value) == (
            "start_time is before the event's publication_time; move the "
            "publication first (update_event)"
        )
        assert uow.agenda_items.created == []

    def test_a_drop_covered_by_adjacent_slots_leaves_the_event_alone(self, uow):
        published = _event(
            start_time=_START + timedelta(days=1),
            publication_time=_START + timedelta(hours=1),
        )
        uow.sessions.read_event.return_value = published
        uow.events.read.side_effect = _lookup({1: published})
        middle = _START + timedelta(minutes=30)
        uow.time_slots.rows = [_slot_from(1, _START, hours=0.5), _slot(middle, _END)]

        _timetable_service(uow).assign_session(
            session_pk=1, placement=self._placement(), event_pk=1
        )

        assert [item["session_id"] for item in uow.agenda_items.created] == [1]
        assert uow.time_slots.created == []
        uow.events.update.assert_not_called()

    def test_a_drop_away_from_every_slot_opens_its_own_window(self, uow):
        far = _slot_from(1, _START + timedelta(days=1), hours=1)
        uow.time_slots.rows = [far]

        _timetable_service(uow).assign_session(
            session_pk=1, placement=self._placement(), event_pk=1, user_pk=4
        )

        assert uow.time_slots.created == [(1, _START, _END)]
        assert [item["session_id"] for item in uow.agenda_items.created] == [1]
        assert uow.schedule_change_logs.created == [
            {
                "event_id": 1,
                "session_id": 1,
                "user_id": 4,
                "action": ScheduleChangeAction.ASSIGN,
                "new_space_id": 1,
                "new_start_time": _START,
                "new_end_time": _END,
                "moved_from_id": None,
            }
        ]


class TestUnassignSession:
    def test_an_unscheduled_session_is_not_found(self):
        uow = _spec_uow(
            agenda_items=_FakeAgendaItems(),
            schedule_change_logs=_FakeScheduleChangeLogs(),
        )
        uow.sessions.read_event.return_value = _event()

        with pytest.raises(NotFoundError):
            _timetable_service(uow).unassign_session(session_pk=1, event_pk=1)

        assert uow.schedule_change_logs.created == []


class TestRevertChangeOutcomes:
    @pytest.fixture
    def uow(self):
        uow = _spec_uow(
            agenda_items=_FakeAgendaItems(),
            schedule_change_logs=_FakeScheduleChangeLogs(),
        )
        uow.sessions.read.side_effect = _lookup({1: _session()})
        uow.sessions.read_event.side_effect = _lookup({1: _event()})
        return uow

    @staticmethod
    def _revert(uow, log_pk=1):
        _timetable_service(uow).revert_change(log_pk=log_pk, event_pk=1, user_pk=4)

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
        uow.agenda_items.rows = {7: _make_item(pk=7, session_id=1, space_id=3)}
        uow.schedule_change_logs.rows = {
            1: _schedule_log(new_space_id=3, new_start_time=_START, new_end_time=_END)
        }

        self._revert(uow)

        uow.sessions.lock.assert_called_once_with(1)
        assert uow.agenda_items.rows == {}
        assert uow.schedule_change_logs.created == [
            {
                "event_id": 1,
                "session_id": 1,
                "user_id": 4,
                "action": ScheduleChangeAction.REVERT,
                "old_space_id": 3,
                "old_start_time": _START,
                "old_end_time": _END,
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
                old_start_time=_START,
                old_end_time=_END,
            )
        }

        self._revert(uow)

        assert uow.agenda_items.created == [
            {
                "session_id": 1,
                "space_id": 3,
                "start_time": _START,
                "end_time": _END,
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
                "new_start_time": _START,
                "new_end_time": _END,
            }
        ]

    @pytest.mark.parametrize(
        "missing", ("old_space_id", "old_start_time", "old_end_time")
    )
    def test_an_unassign_missing_any_part_of_its_placement_cannot_revert(
        self, uow, missing
    ):
        placement = {"old_space_id": 3, "old_start_time": _START, "old_end_time": _END}
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

    def test_a_revert_row_itself_cannot_be_reverted(self, uow):
        uow.schedule_change_logs.rows = {
            1: _schedule_log(action=ScheduleChangeAction.REVERT)
        }

        with pytest.raises(ValueError, match="Cannot revert action"):
            self._revert(uow)

        assert uow.schedule_change_logs.created == []


class TestDetectForAssignment:
    @pytest.fixture
    def uow(self):
        uow = _spec_uow(
            agenda_items=_FakeAgendaItems(
                _make_item(pk=1, session_id=10, space_id=1, session_title="Mine"),
                _make_item(pk=2, session_id=20, space_id=1, session_title="Theirs"),
            )
        )
        uow.spaces.list_by_event.return_value = [_space(1)]
        _stub_warning_reads(uow)
        return uow

    def test_reports_the_placed_sessions_clashes(self, uow):
        conflicts = _conflict_service(uow).detect_for_assignment(
            event_pk=1, session_pk=10
        )

        assert [(c.type, c.subject_session_pk, c.session_pk) for c in conflicts] == [
            (ConflictType.SPACE_OVERLAP, 10, 20)
        ]

    def test_reports_a_room_too_small_for_the_session(self, uow):
        uow.agenda_items.rows = {1: _make_item(pk=1, session_id=10, space_id=1)}
        uow.spaces.list_by_event.return_value = [_space(1, capacity=_ROOM_CAPACITY)]
        uow.sessions.read_participants_limits.side_effect = _subset(
            {10: _SESSION_LIMIT}
        )

        conflicts = _conflict_service(uow).detect_for_assignment(
            event_pk=1, session_pk=10
        )

        assert [(c.type, c.space_capacity, c.session_limit) for c in conflicts] == [
            (ConflictType.CAPACITY_EXCEEDED, _ROOM_CAPACITY, _SESSION_LIMIT)
        ]

    def test_a_session_without_a_limit_fits_a_room_of_no_capacity(self, uow):
        uow.agenda_items.rows = {1: _make_item(pk=1, session_id=10, space_id=1)}
        uow.spaces.list_by_event.return_value = [_space(1, capacity=0)]

        conflicts = _conflict_service(uow).detect_for_assignment(
            event_pk=1, session_pk=10
        )

        assert not conflicts

    def test_an_unscheduled_session_is_not_found(self, uow):
        with pytest.raises(NotFoundError):
            _conflict_service(uow).detect_for_assignment(event_pk=1, session_pk=30)


class TestTrackAttribution:
    @pytest.fixture
    def uow(self):
        shared = _facilitator(7, display_name="Alice")
        uow = _spec_uow(
            agenda_items=_FakeAgendaItems(
                _make_item(pk=1, session_id=10, space_id=1, session_title="Mine"),
                _make_item(pk=2, session_id=20, space_id=2, session_title="Theirs"),
            )
        )
        uow.agenda_items.by_track = {3: [uow.agenda_items.rows[1]]}
        uow.spaces.list_by_event.return_value = [_space(1), _space(2)]
        _stub_warning_reads(uow)
        uow.sessions.read_facilitators_by_sessions.side_effect = _subset(
            {10: [shared], 20: [shared]}
        )
        uow.sessions.list_track_names_by_session.side_effect = _subset(
            {20: {3: "Zeta", 5: "Alpha"}}
        )
        uow.tracks.list_manager_names_by_tracks.side_effect = _subset({5: ["Ann"]})
        uow.tracks.read.side_effect = _lookup({3: _track(3)})
        return uow

    def test_a_facilitator_clash_names_the_other_sessions_track(self, uow):
        conflicts = _conflict_service(uow).list_all_for_track(event_pk=1, track_pk=None)

        assert [
            (c.type, c.facilitator_name, c.track_name, c.manager_names)
            for c in conflicts
        ] == [(ConflictType.FACILITATOR_OVERLAP, "Alice", "Alpha", ["Ann"])]

    def test_a_foreign_track_without_managers_is_still_named(self, uow):
        uow.tracks.list_manager_names_by_tracks.side_effect = _subset({})

        conflicts = _conflict_service(uow).list_all_for_track(event_pk=1, track_pk=None)

        assert [(c.track_name, c.manager_names) for c in conflicts] == [("Alpha", [])]

    def test_only_facilitator_clashes_are_attributed(self, uow):
        uow.agenda_items.rows[2] = _make_item(
            pk=2, session_id=20, space_id=1, session_title="Theirs"
        )

        conflicts = _conflict_service(uow).list_all_for_track(event_pk=1, track_pk=None)

        assert [(c.type, c.track_name) for c in conflicts] == [
            (ConflictType.SPACE_OVERLAP, None),
            (ConflictType.FACILITATOR_OVERLAP, "Alpha"),
        ]

    def test_the_current_track_is_never_named_as_foreign(self, uow):
        uow.sessions.list_track_names_by_session.side_effect = _subset(
            {20: {3: "Alpha"}}
        )

        conflicts = _conflict_service(uow).list_all_for_track(event_pk=1, track_pk=3)

        assert [(c.track_name, c.manager_names) for c in conflicts] == [(None, [])]

    def test_a_track_listing_only_reports_its_own_sessions_clashes(self, uow):
        uow.agenda_items.rows[3] = _make_item(pk=3, session_id=30, space_id=9)
        uow.agenda_items.rows[4] = _make_item(pk=4, session_id=40, space_id=9)

        conflicts = _conflict_service(uow).list_all_for_track(event_pk=1, track_pk=3)

        assert [(c.subject_session_pk, c.session_pk) for c in conflicts] == [(10, 20)]

    def test_a_foreign_track_is_not_found(self, uow):
        uow.tracks.read.side_effect = _lookup(
            {3: TrackDTO(**(_track(3).model_dump() | {"event_id": 2}))}
        )

        with pytest.raises(NotFoundError):
            _conflict_service(uow).list_all_for_track(event_pk=1, track_pk=3)


class TestPreferredSlotViolations:
    @pytest.fixture
    def uow(self):
        free = _make_item(pk=1, session_id=30, session_title="Free")
        inside = _make_item(pk=2, session_id=10, session_title="Inside")
        outside = _make_item(
            pk=3,
            session_id=20,
            session_title="Outside",
            start_time=_START + timedelta(hours=5),
            end_time=_END + timedelta(hours=5),
        )
        elsewhere = _make_item(
            pk=4,
            session_id=40,
            session_title="Elsewhere",
            start_time=_START + timedelta(hours=5),
            end_time=_END + timedelta(hours=5),
        )
        uow = _spec_uow(agenda_items=_FakeAgendaItems(free, inside, outside, elsewhere))
        uow.agenda_items.by_track = {3: [free, inside, outside]}
        _stub_warning_reads(uow)
        uow.sessions.read_preferred_time_slots_by_sessions.side_effect = _subset(
            {
                10: [_slot(_START, _END)],
                20: [_slot(_START, _END)],
                40: [_slot(_START, _END)],
            }
        )
        uow.tracks.read.side_effect = _lookup({3: _track(3)})
        return uow

    @pytest.mark.parametrize(
        ("track_pk", "titles"), ((None, ["Outside", "Elsewhere"]), (3, ["Outside"]))
    )
    def test_only_sessions_outside_their_picks_are_reported(
        self, uow, track_pk, titles
    ):
        violations = _conflict_service(uow).list_preferred_slot_violations(
            event_pk=1, track_pk=track_pk
        )

        assert [(v.session_title, v.track_name) for v in violations] == [
            (title, None) for title in titles
        ]

    def test_a_violation_names_the_sessions_foreign_track(self, uow):
        uow.sessions.list_track_names_by_session.side_effect = _subset(
            {20: {3: "Alpha", 5: "Beta"}}
        )
        uow.tracks.list_manager_names_by_tracks.side_effect = _subset({5: ["Bob"]})

        violations = _conflict_service(uow).list_preferred_slot_violations(
            event_pk=1, track_pk=3
        )

        assert [(v.session_pk, v.track_name, v.manager_names) for v in violations] == [
            (20, "Beta", ["Bob"])
        ]


class TestListGridWarnings:
    def test_warnings_are_about_the_tracks_sessions_and_name_foreign_tracks(self):
        shared = _facilitator(7)
        mine = _make_item(pk=1, session_id=10, space_id=1, session_title="Mine")
        theirs = _make_item(pk=2, session_id=20, space_id=2, session_title="Theirs")
        uow = _spec_uow(agenda_items=_FakeAgendaItems(mine, theirs))
        uow.agenda_items.by_track = {3: [mine]}
        _stub_warning_reads(uow)
        uow.sessions.read_facilitators_by_sessions.side_effect = _subset(
            {10: [shared], 20: [shared]}
        )
        far = _slot(_START + timedelta(days=1), _END + timedelta(days=1))
        uow.sessions.read_preferred_time_slots_by_sessions.side_effect = _subset(
            {10: [far], 20: [far]}
        )
        uow.sessions.list_track_names_by_session.side_effect = _subset(
            {10: {3: "Alpha"}, 20: {3: "Alpha"}}
        )
        uow.tracks.list_manager_names_by_tracks.side_effect = _subset({3: ["Ann"]})
        uow.tracks.read.side_effect = _lookup({3: _track(3)})

        conflicts, violations = _conflict_service(uow).list_grid_warnings(
            event_pk=1, track_pk=3, items=[mine, theirs], spaces=[_space(1), _space(2)]
        )

        assert [
            (c.type, c.subject_session_pk, c.session_pk, c.track_name)
            for c in conflicts
        ] == [(ConflictType.FACILITATOR_OVERLAP, 10, 20, None)]
        assert [(v.session_pk, v.track_name) for v in violations] == [(10, None)]


class TestOverviewConflicts:
    @pytest.fixture
    def uow(self):
        uow = _spec_uow(
            agenda_items=_FakeAgendaItems(
                _make_item(pk=1, session_id=10, space_id=3, session_title="Mine"),
                _make_item(pk=2, session_id=20, space_id=3, session_title="Theirs"),
            )
        )
        uow.spaces.list_by_event.side_effect = _lookup({1: [_space(3)]})
        uow.time_slots.list_by_event.side_effect = _lookup({1: [_slot(_START, _END)]})
        _stub_warning_reads(uow)
        return uow

    def test_heatmap_detects_conflicts_when_none_are_handed_in(self, uow):
        result = _overview_service(uow).build_heatmap(event_pk=1, tz=UTC)

        assert [c.status for c in result.rows[0].cells] == [HeatmapCellStatus.CONFLICT]

    def test_heatmap_ignores_bookings_on_branch_spaces(self, uow):
        uow.spaces.list_by_event.side_effect = _lookup(
            {1: [_space(1), _space(3, parent_id=1)]}
        )
        uow.agenda_items.rows = {1: _make_item(pk=1, session_id=10, space_id=1)}

        result = _overview_service(uow).build_heatmap(event_pk=1, tz=UTC, conflicts=[])

        assert [c.status for c in result.rows[0].cells] == [HeatmapCellStatus.EMPTY]

    def test_heatmap_rounds_a_partial_last_hour_up(self, uow):
        uow.time_slots.list_by_event.side_effect = _lookup(
            {1: [_slot(_START, _END + timedelta(minutes=30))]}
        )

        result = _overview_service(uow).build_heatmap(event_pk=1, tz=UTC, conflicts=[])

        assert [row.time.strftime("%H:%M") for row in result.rows] == ["10:00", "11:00"]

    def test_grouping_detects_conflicts_when_none_are_handed_in(self, uow):
        grouped = _overview_service(uow).all_conflicts_grouped(event_pk=1)

        assert list(grouped) == [ConflictType.SPACE_OVERLAP]
        assert [c.session_pk for c in grouped[ConflictType.SPACE_OVERLAP]] == [20]

    def test_grouping_keeps_each_type_together(self, uow):
        def conflict(kind, pk):
            return ConflictDTO(
                type=kind,
                severity=ConflictSeverity.ERROR,
                subject_session_title="",
                subject_session_pk=1,
                session_title="",
                session_pk=pk,
            )

        conflicts = [
            conflict(ConflictType.SPACE_OVERLAP, 2),
            conflict(ConflictType.FACILITATOR_OVERLAP, 3),
            conflict(ConflictType.SPACE_OVERLAP, 4),
        ]

        grouped = _overview_service(uow).all_conflicts_grouped(
            event_pk=1, conflicts=conflicts
        )

        assert {k: [c.session_pk for c in v] for k, v in grouped.items()} == {
            ConflictType.SPACE_OVERLAP: [2, 4],
            ConflictType.FACILITATOR_OVERLAP: [3],
        }


class TestTrackProgress:
    def test_no_tracks_means_no_rows(self):
        uow = _spec_uow()
        uow.tracks.list_by_event.return_value = []

        assert not _overview_service(uow).track_progress(event_pk=1)

    def test_progress_is_measured_against_the_active_pool(self):
        uow = _spec_uow()
        uow.tracks.list_by_event.side_effect = _lookup(
            {1: [_track(1, "Busy"), _track(2, "Empty")]}
        )
        uow.sessions.count_by_track.side_effect = _lookup(
            {
                1: {
                    1: TrackSessionCountsDTO(
                        pending=1, accepted=3, scheduled=2, on_hold=1, rejected=5
                    )
                }
            }
        )
        uow.tracks.list_manager_names_by_tracks.side_effect = _subset({1: ["Ann"]})

        assert _overview_service(uow).track_progress(event_pk=1) == [
            TrackProgressDTO(
                track_pk=1,
                track_name="Busy",
                manager_names=["Ann"],
                accepted_count=3,
                scheduled_count=2,
                pending_count=1,
                on_hold_count=1,
                rejected_count=5,
                progress_pct=50,
            ),
            TrackProgressDTO(
                track_pk=2,
                track_name="Empty",
                manager_names=[],
                accepted_count=0,
                scheduled_count=0,
                progress_pct=0,
            ),
        ]

    def test_on_hold_sessions_are_reported_but_not_counted_as_active(self):
        uow = _spec_uow()
        uow.tracks.list_by_event.return_value = [_track(1, "RPG")]
        uow.sessions.count_by_track.return_value = {
            1: TrackSessionCountsDTO(pending=1, accepted=2, scheduled=1, on_hold=5)
        }
        uow.tracks.list_manager_names_by_tracks.return_value = {}

        assert _overview_service(uow).track_progress(event_pk=1) == [
            TrackProgressDTO(
                track_pk=1,
                track_name="RPG",
                manager_names=[],
                accepted_count=2,
                scheduled_count=1,
                pending_count=1,
                on_hold_count=5,
                rejected_count=0,
                progress_pct=33,
            )
        ]
