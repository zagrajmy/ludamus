from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock, call

import pytest

from ludamus.mills.timetable import (
    ConflictDetectionService,
    TimetableOverviewService,
    TimetableService,
)
from ludamus.pacts import (
    AgendaItemDTO,
    NotFoundError,
    ScheduleChangeAction,
    SessionStatus,
    SpaceDTO,
    TimeSlotDTO,
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
    TimetableGridFilter,
    TrackProgressDTO,
)
from ludamus.pacts.timetable import (
    PlacementRejectedError,
    PlacementRejection,
    TimetableRepos,
)

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
        "session_confirmed": False,
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

    def test_all_days_share_rooms_and_load_agenda_once(self):
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
        uow.agenda_items.list_by_event.assert_called_once_with(1)
        uow.spaces.list_by_event.assert_called_once_with(1)

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
        uow.tracks.list_space_pks.return_value = [1]
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
        uow.tracks.read.return_value = _event_track(event_pk=1)
        uow.sessions.read_facilitators_by_sessions.return_value = {}
        uow.sessions.read_participants_limits.return_value = {}
        uow.sessions.read_preferred_time_slots_by_sessions.return_value = {}
        uow.sessions.list_track_names_by_session.return_value = {}
        uow.tracks.list_manager_names_by_tracks.return_value = {}

        grid = _timetable_service(uow).build_grid(
            event_pk=1, tz=UTC, filters=TimetableGridFilter(track_pk=5)
        )

        sessions = grid.days[0].columns[0].sessions
        assert [(pos.agenda_item.session_title, pos.state) for pos in sessions] == [
            ("Mine", "conflict"),
            ("Theirs", "conflict"),
            ("Untracked", "normal"),
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
        friday, saturday = day_one.columns[0].sessions[0], (
            day_two.columns[0].sessions[0]
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

    def test_options_list_every_node_with_its_depth(self, uow):
        options = _timetable_service(uow).space_filter_options(1)

        assert [(o.value, o.label, o.depth) for o in options] == [
            (1, "Building A", 0),
            (2, "Floor 2", 1),
            (3, "Room 201", 2),
            (4, "Room 202", 2),
            (5, "Building B", 0),
            (6, "Room 1", 1),
        ]

    def test_unfiltered_grid_shows_every_leaf(self, uow):
        grid = _timetable_service(uow).build_grid(event_pk=1, tz=UTC)

        assert [space.pk for space in grid.spaces] == [3, 4, 6]

    def test_grid_uses_programme_order_instead_of_tree_order(self, uow):
        by_pk = {space.pk: space for space in uow.spaces.list_by_event.return_value}
        by_pk[6].programme_order = 0
        by_pk[3].programme_order = 1
        by_pk[4].programme_order = 2

        grid = _timetable_service(uow).build_grid(event_pk=1, tz=UTC)

        assert [space.pk for space in grid.spaces] == [6, 3, 4]

    @staticmethod
    def _grid_for(uow, space_pks):
        return _timetable_service(uow).build_grid(
            event_pk=1, tz=UTC, filters=TimetableGridFilter(space_pks=space_pks)
        )

    def test_selecting_a_branch_keeps_every_leaf_under_it(self, uow):
        grid = self._grid_for(uow, {2})

        assert [space.pk for space in grid.spaces] == [3, 4]

    def test_selecting_a_leaf_keeps_only_that_leaf(self, uow):
        grid = self._grid_for(uow, {3})

        assert [space.pk for space in grid.spaces] == [3]

    def test_branch_and_leaf_selections_union(self, uow):
        grid = self._grid_for(uow, {2, 6})

        assert [space.pk for space in grid.spaces] == [3, 4, 6]

    def test_pk_from_another_event_matches_nothing(self, uow):
        grid = self._grid_for(uow, {999})

        assert grid.spaces == []


class TestFacilitatorFilter:
    @pytest.fixture
    def uow(self):
        now = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        uow = MagicMock()
        uow.spaces.list_by_event.return_value = [
            SpaceDTO(
                capacity=None,
                creation_time=now,
                modification_time=now,
                name="Room 1",
                order=0,
                pk=1,
                slug="room-1",
            )
        ]
        uow.time_slots.list_by_event.return_value = [
            TimeSlotDTO(
                pk=1,
                start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                end_time=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
            )
        ]
        uow.agenda_items.list_by_event.return_value = [
            _make_item(pk=1, session_id=1),
            _make_item(
                pk=2,
                session_id=2,
                start_time=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
                end_time=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
            ),
        ]
        return uow

    @staticmethod
    def _session_pks(grid):
        return [
            pos.agenda_item.session_id
            for day in grid.days
            for col in day.columns
            for pos in col.sessions
        ]

    def test_no_facilitator_picked_asks_for_every_item(self, uow):
        grid = _timetable_service(uow).build_grid(event_pk=1, tz=UTC)

        assert self._session_pks(grid) == [1, 2]
        uow.agenda_items.list_by_event.assert_called_once_with(1)

    def test_picking_a_facilitator_narrows_the_query(self, uow):
        uow.agenda_items.list_by_event.side_effect = [
            [_make_item(pk=1, session_id=1), _make_item(pk=2, session_id=2)],
            [_make_item(pk=1, session_id=1)],
        ]

        grid = _timetable_service(uow).build_grid(
            event_pk=1, tz=UTC, filters=TimetableGridFilter(facilitator_pks={7})
        )

        assert self._session_pks(grid) == [1]
        assert uow.agenda_items.list_by_event.call_args_list == [
            call(1),
            call(1, facilitator_pks={7}),
        ]

    def test_several_facilitators_reach_the_query_as_one_set(self, uow):
        _timetable_service(uow).build_grid(
            event_pk=1, tz=UTC, filters=TimetableGridFilter(facilitator_pks={7, 8})
        )

        assert uow.agenda_items.list_by_event.call_args_list == [
            call(1),
            call(1, facilitator_pks={7, 8}),
        ]

    def test_facilitator_with_nothing_scheduled_empties_the_grid(self, uow):
        uow.agenda_items.list_by_event.return_value = []

        grid = _timetable_service(uow).build_grid(
            event_pk=1, tz=UTC, filters=TimetableGridFilter(facilitator_pks={7})
        )

        assert self._session_pks(grid) == []


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

    def test_revert_rejects_non_latest_change(self, service, mock_uow):
        log = MagicMock()
        log.event_id = 1
        log.action = ScheduleChangeAction.ASSIGN
        log.session_id = 7
        mock_uow.schedule_change_logs.read.return_value = log
        mock_uow.schedule_change_logs.latest_pk_for_session.return_value = 2

        with pytest.raises(
            ValueError, match=r"^Only the latest change for a session can be reverted$"
        ):
            service.revert_change(log_pk=3, event_pk=1)

        mock_uow.schedule_change_logs.read.assert_called_once_with(3)
        mock_uow.sessions.lock.assert_called_once_with(7)
        mock_uow.schedule_change_logs.latest_pk_for_session.assert_called_once_with(
            1, 7
        )
        mock_uow.agenda_items.read_by_session.assert_not_called()

    def test_revert_raises_not_found_for_log_from_another_event(
        self, service, mock_uow
    ):
        log = MagicMock()
        log.event_id = 2
        log.action = ScheduleChangeAction.ASSIGN
        log.session_id = 1
        mock_uow.schedule_change_logs.read.return_value = log

        with pytest.raises(NotFoundError):
            service.revert_change(log_pk=1, event_pk=1)

        mock_uow.agenda_items.read_by_session.assert_not_called()

    def test_revert_assign_raises_not_found_when_no_agenda_item(
        self, service, mock_uow
    ):
        log = MagicMock()
        log.event_id = 1
        log.action = ScheduleChangeAction.ASSIGN
        log.session_id = 1
        mock_uow.schedule_change_logs.read.return_value = log
        mock_uow.agenda_items.read_by_session.return_value = None

        with pytest.raises(NotFoundError):
            service.revert_change(log_pk=1, event_pk=1)

    @pytest.mark.parametrize(
        "missing", ("old_space_id", "old_start_time", "old_end_time")
    )
    def test_revert_unassign_raises_when_missing_placement_data(
        self, service, mock_uow, missing
    ):
        log = MagicMock()
        log.event_id = 1
        log.action = ScheduleChangeAction.UNASSIGN
        log.session_id = 1
        log.old_space_id = 5
        log.old_start_time = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        log.old_end_time = datetime(2026, 1, 1, 11, 0, tzinfo=UTC)
        setattr(log, missing, None)
        mock_uow.schedule_change_logs.read.return_value = log

        with pytest.raises(
            ValueError,
            match=r"^Cannot revert UNASSIGN: missing original placement data$",
        ):
            service.revert_change(log_pk=1, event_pk=1)

        mock_uow.agenda_items.create.assert_not_called()

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
        mock_uow.agenda_items.create.assert_not_called()

    def test_revert_unassign_restores_the_original_placement(self, service, mock_uow):
        log = MagicMock()
        log.event_id = 1
        log.action = ScheduleChangeAction.UNASSIGN
        log.session_id = 7
        log.old_space_id = 5
        log.old_start_time = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        log.old_end_time = datetime(2026, 1, 1, 11, 0, tzinfo=UTC)
        mock_uow.schedule_change_logs.read.return_value = log
        mock_uow.schedule_change_logs.latest_pk_for_session.return_value = 3
        mock_uow.sessions.read.return_value.status = SessionStatus.ACCEPTED
        mock_uow.sessions.read_event.return_value.pk = 1

        service.revert_change(log_pk=3, event_pk=1, user_pk=9)

        mock_uow.sessions.read.assert_called_once_with(7)
        mock_uow.sessions.read_event.assert_called_once_with(7)
        mock_uow.agenda_items.read_by_session.assert_not_called()
        mock_uow.agenda_items.delete.assert_not_called()
        mock_uow.agenda_items.create.assert_called_once_with(
            {
                "session_id": 7,
                "space_id": 5,
                "start_time": log.old_start_time,
                "end_time": log.old_end_time,
                "session_confirmed": False,
            }
        )
        mock_uow.schedule_change_logs.create.assert_called_once_with(
            {
                "event_id": 1,
                "session_id": 7,
                "user_id": 9,
                "action": ScheduleChangeAction.REVERT,
                "new_space_id": 5,
                "new_start_time": log.old_start_time,
                "new_end_time": log.old_end_time,
            }
        )

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

    def test_revert_unknown_action_raises(self, service, mock_uow):
        log = MagicMock()
        log.event_id = 1
        log.action = "UNKNOWN_ACTION"
        log.session_id = 1
        mock_uow.schedule_change_logs.read.return_value = log

        with pytest.raises(ValueError, match="Cannot revert action"):
            service.revert_change(log_pk=1, event_pk=1)


class TestAssignUnassignScope:
    """The service rejects sessions/spaces that belong to another event."""

    @pytest.fixture
    def mock_uow(self):
        return MagicMock()

    @pytest.fixture
    def service(self, mock_uow):
        return _timetable_service(mock_uow)

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

    def test_assign_rejects_session_from_another_event(self, service, mock_uow):
        mock_uow.sessions.read_event.return_value = self._event(2)

        with pytest.raises(NotFoundError):
            service.assign_session(
                session_pk=1, placement=self._placement(), event_pk=1
            )

        mock_uow.agenda_items.create.assert_not_called()

    def test_assign_rejects_space_from_another_event(self, service, mock_uow):
        mock_uow.sessions.read_event.return_value = self._event(1)
        foreign_space = MagicMock()
        foreign_space.pk = 99
        mock_uow.spaces.list_by_event.return_value = [foreign_space]

        with pytest.raises(NotFoundError):
            service.assign_session(
                session_pk=1, placement=self._placement(), event_pk=1
            )

        mock_uow.agenda_items.create.assert_not_called()

    def test_unassign_rejects_session_from_another_event(self, service, mock_uow):
        mock_uow.sessions.read_event.return_value = self._event(2)

        with pytest.raises(NotFoundError):
            service.unassign_session(session_pk=1, event_pk=1)

        mock_uow.agenda_items.delete.assert_not_called()

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

    def test_unassign_log_failure_rolls_back_inside_atomic(self, service, mock_uow):
        mock_uow.sessions.read_event.return_value = self._event(1)
        agenda_item = MagicMock()
        agenda_item.pk = 5
        agenda_item.space_id = 2
        agenda_item.start_time = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        agenda_item.end_time = datetime(2026, 1, 1, 11, 0, tzinfo=UTC)
        mock_uow.agenda_items.read_by_session.return_value = agenda_item
        mock_uow.schedule_change_logs.create.side_effect = RuntimeError("log failed")

        with pytest.raises(RuntimeError, match="log failed"):
            service.unassign_session(session_pk=1, event_pk=1)

        mock_uow.atomic.assert_called_once()
        mock_uow.sessions.lock.assert_called_once_with(1)
        mock_uow.agenda_items.delete.assert_called_once_with(agenda_item.pk)
        mock_uow.schedule_change_logs.create.assert_called_once()

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
        mock_uow.time_slots.list_by_event.return_value = [
            _slot_from(1, placement.start_time, hours=1)
        ]
        session = MagicMock()
        session.status = SessionStatus.ACCEPTED
        mock_uow.sessions.read.return_value = session

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

    def test_assign_inside_the_time_slots_leaves_them_alone(self, service, mock_uow):
        self._arrange_acceptable_assignment(mock_uow, auto_confirm_sessions=True)

        service.assign_session(session_pk=1, placement=self._placement(), event_pk=1)

        mock_uow.time_slots.list_by_event.assert_called_once_with(1)
        mock_uow.time_slots.update.assert_not_called()
        mock_uow.time_slots.create.assert_not_called()
        mock_uow.events.lock.assert_not_called()
        mock_uow.events.read.assert_not_called()
        mock_uow.events.update.assert_not_called()

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

    def test_assign_starting_before_a_slot_stretches_it_back(self, service, mock_uow):
        self._arrange_acceptable_assignment(mock_uow, auto_confirm_sessions=True)
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
        self._arrange_acceptable_assignment(mock_uow, auto_confirm_sessions=True)
        placement = self._placement()
        after = _slot_from(1, placement.end_time, hours=1)
        mock_uow.time_slots.list_by_event.return_value = [after]

        service.assign_session(session_pk=1, placement=placement, event_pk=1)

        mock_uow.time_slots.update.assert_called_once_with(
            1, placement.start_time, after.end_time
        )
        mock_uow.time_slots.create.assert_not_called()

    def test_assign_away_from_every_slot_opens_its_own_window(self, service, mock_uow):
        self._arrange_acceptable_assignment(mock_uow, auto_confirm_sessions=True)
        placement = self._placement()
        morning = _slot_from(1, placement.start_time - timedelta(hours=4), hours=2)
        afternoon = _slot_from(2, placement.start_time - timedelta(hours=1), hours=0.5)
        mock_uow.time_slots.list_by_event.return_value = [afternoon, morning]

        service.assign_session(session_pk=1, placement=placement, event_pk=1)

        mock_uow.time_slots.update.assert_not_called()
        mock_uow.time_slots.create.assert_called_once_with(
            1, placement.start_time, placement.end_time
        )
        mock_uow.agenda_items.create.assert_called_once()

    def test_assign_touching_a_slot_stretches_it_to_the_placement(
        self, service, mock_uow
    ):
        self._arrange_acceptable_assignment(mock_uow, auto_confirm_sessions=True)
        placement = self._placement()
        before = _slot_from(1, placement.start_time - timedelta(hours=1), hours=1)
        mock_uow.time_slots.list_by_event.return_value = [before]

        service.assign_session(session_pk=1, placement=placement, event_pk=1)

        mock_uow.time_slots.update.assert_called_once_with(
            1, before.start_time, placement.end_time
        )
        mock_uow.time_slots.create.assert_not_called()

    def test_assign_across_a_gap_closes_it(self, service, mock_uow):
        self._arrange_acceptable_assignment(mock_uow, auto_confirm_sessions=True)
        placement = self._placement()
        before = _slot_from(1, placement.start_time - timedelta(minutes=30), hours=0.75)
        after = _slot_from(2, placement.start_time + timedelta(minutes=45), hours=1)
        mock_uow.time_slots.list_by_event.return_value = [before, after]

        service.assign_session(session_pk=1, placement=placement, event_pk=1)

        mock_uow.time_slots.update.assert_called_once_with(
            1, before.start_time, after.start_time
        )

    def test_assign_with_no_time_slots_creates_one_around_it(self, service, mock_uow):
        self._arrange_acceptable_assignment(mock_uow, auto_confirm_sessions=True)
        placement = self._placement()
        mock_uow.time_slots.list_by_event.return_value = []

        service.assign_session(session_pk=1, placement=placement, event_pk=1)

        mock_uow.time_slots.create.assert_called_once_with(
            1, placement.start_time, placement.end_time
        )

    def test_assign_past_the_event_end_widens_the_event(self, service, mock_uow):
        self._arrange_acceptable_assignment(mock_uow, auto_confirm_sessions=True)
        placement = self._placement()
        event = mock_uow.sessions.read_event.return_value
        event.start_time = placement.start_time - timedelta(days=1)
        event.end_time = placement.start_time + timedelta(minutes=30)
        event.publication_time = None
        mock_uow.time_slots.list_by_event.return_value = [
            _slot_from(1, event.start_time, hours=1)
        ]

        service.assign_session(session_pk=1, placement=placement, event_pk=1)

        mock_uow.events.update.assert_called_once_with(
            1, {"end_time": placement.end_time}
        )

    def test_assign_before_publication_is_refused_without_writing(
        self, service, mock_uow
    ):
        self._arrange_acceptable_assignment(mock_uow, auto_confirm_sessions=True)
        placement = self._placement()
        event = mock_uow.sessions.read_event.return_value
        event.start_time = placement.end_time
        event.end_time = placement.end_time + timedelta(days=1)
        event.publication_time = placement.start_time + timedelta(minutes=30)
        mock_uow.time_slots.list_by_event.return_value = [
            _slot_from(1, event.start_time, hours=1)
        ]

        with pytest.raises(PlacementRejectedError) as excinfo:
            service.assign_session(session_pk=1, placement=placement, event_pk=1)

        assert excinfo.value.reason is PlacementRejection.BEFORE_PUBLICATION
        assert str(excinfo.value) == (
            "start_time is before the event's publication_time; move the "
            "publication first (update_event)"
        )

        mock_uow.events.update.assert_not_called()
        mock_uow.time_slots.update.assert_not_called()
        mock_uow.agenda_items.create.assert_not_called()

    def test_assign_accepts_a_placement_across_adjacent_time_slots(
        self, service, mock_uow
    ):
        self._arrange_acceptable_assignment(mock_uow, auto_confirm_sessions=True)
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

    def test_assign_rejects_a_session_that_is_not_accepted(self, service, mock_uow):
        self._arrange_acceptable_assignment(mock_uow, auto_confirm_sessions=True)
        mock_uow.sessions.read.return_value.status = SessionStatus.PENDING

        with pytest.raises(PlacementRejectedError, match="is not in ACCEPTED status"):
            service.assign_session(
                session_pk=1, placement=self._placement(), event_pk=1
            )

        mock_uow.agenda_items.create.assert_not_called()

    def test_assign_writes_the_placement_and_its_log(self, service, mock_uow):
        self._arrange_acceptable_assignment(mock_uow, auto_confirm_sessions=True)
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

    def test_assign_leaves_unconfirmed_when_event_disables_auto_confirm(
        self, service, mock_uow
    ):
        self._arrange_acceptable_assignment(mock_uow, auto_confirm_sessions=False)

        service.assign_session(session_pk=1, placement=self._placement(), event_pk=1)

        created = mock_uow.agenda_items.create.call_args.args[0]
        assert created["session_confirmed"] is False

    def test_move_unconfirms_even_when_event_auto_confirms(self, service, mock_uow):
        self._arrange_acceptable_assignment(mock_uow, auto_confirm_sessions=True)
        mock_uow.agenda_items.read_by_session.return_value = MagicMock()

        service.assign_session(session_pk=1, placement=self._placement(), event_pk=1)

        created = mock_uow.agenda_items.create.call_args.args[0]
        assert created["session_confirmed"] is False

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

    def test_a_plain_assignment_leaves_nothing_behind(self, service, mock_uow):
        self._arrange_acceptable_assignment(mock_uow, auto_confirm_sessions=True)

        service.assign_session(session_pk=1, placement=self._placement(), event_pk=1)

        assign_log = mock_uow.schedule_change_logs.create.call_args.args[0]
        assert assign_log["moved_from_id"] is None


def _facilitator(pk, display_name="Alice", *, is_collective=False):
    facilitator = MagicMock()
    facilitator.pk = pk
    facilitator.display_name = display_name
    facilitator.is_collective = is_collective
    return facilitator


def _track_stub(pk, name="Track"):
    track = MagicMock()
    track.pk = pk
    track.name = name
    return track


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
    """Batched conflict detection: repos are hit once, overlaps found in memory."""

    @staticmethod
    def _uow(*, all_items, subjects=None, spaces=(), limits=None, facilitators=None):
        uow = MagicMock()
        uow.agenda_items.list_by_event.return_value = all_items
        uow.agenda_items.list_by_track.return_value = (
            all_items if subjects is None else subjects
        )
        uow.spaces.list_by_event.return_value = list(spaces)
        uow.sessions.read_participants_limits.return_value = (
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

    def test_capacity_check_skips_a_session_missing_from_limits(self):
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
        uow = self._uow(all_items=[item], spaces=[space], limits={})

        conflicts = _conflict_service(uow).list_all_for_track(event_pk=1, track_pk=None)

        assert not conflicts

    def test_facilitator_overlap_across_tracks_gets_attribution(self):
        subject = _make_item(pk=1, session_id=10, space_id=1)
        other = _make_item(pk=2, session_id=20, space_id=2, session_title="Other")
        shared = _facilitator(7)
        uow = self._uow(
            all_items=[subject, other],
            subjects=[subject],
            facilitators={10: [shared], 20: [shared]},
        )
        uow.sessions.list_track_names_by_session.return_value = {20: {6: "Board games"}}
        uow.tracks.list_manager_names_by_tracks.return_value = {6: ["Basia"]}

        conflicts = _conflict_service(uow).list_all_for_track(event_pk=1, track_pk=5)

        assert len(conflicts) == 1
        conflict = conflicts[0]
        assert conflict.type == ConflictType.FACILITATOR_OVERLAP
        assert conflict.facilitator_name == "Alice"
        assert conflict.track_name == "Board games"
        assert conflict.manager_names == ["Basia"]
        uow.sessions.list_track_names_by_session.assert_called_once_with([20])
        uow.tracks.list_manager_names_by_tracks.assert_called_once_with({6})

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

    def test_attribution_names_the_first_foreign_track_by_name(self):
        subject = _make_item(pk=1, session_id=10, space_id=1)
        other = _make_item(pk=2, session_id=20, space_id=2, session_title="Other")
        shared = _facilitator(7)
        uow = self._uow(
            all_items=[subject, other],
            subjects=[subject],
            facilitators={10: [shared], 20: [shared]},
        )
        uow.sessions.list_track_names_by_session.return_value = {
            20: {6: "Wargames", 7: "Board games"}
        }
        uow.tracks.list_manager_names_by_tracks.return_value = {7: ["Basia"]}

        conflicts = _conflict_service(uow).list_all_for_track(event_pk=1, track_pk=5)

        assert conflicts[0].track_name == "Board games"
        assert conflicts[0].manager_names == ["Basia"]
        uow.tracks.list_manager_names_by_tracks.assert_called_once_with({7})

    def test_no_other_tracks_returns_conflict_unchanged(self):
        current_track_pk = 5
        subject = _make_item(pk=1, session_id=10, space_id=1)
        other = _make_item(pk=2, session_id=20, space_id=2, session_title="Other")
        shared = _facilitator(7)
        uow = self._uow(
            all_items=[subject, other],
            subjects=[subject],
            facilitators={10: [shared], 20: [shared]},
        )
        uow.sessions.list_track_names_by_session.return_value = {
            20: {current_track_pk: "Track"}
        }

        conflicts = _conflict_service(uow).list_all_for_track(
            event_pk=1, track_pk=current_track_pk
        )

        facilitator_conflicts = [
            c for c in conflicts if c.type == ConflictType.FACILITATOR_OVERLAP
        ]
        assert len(facilitator_conflicts) > 0
        for conflict in facilitator_conflicts:
            assert conflict.track_name is None
            assert conflict.manager_names == []

    def test_no_per_item_repo_calls(self):
        items = [
            _make_item(pk=n, session_id=n * 10, space_id=n, session_title=f"S{n}")
            for n in range(1, 6)
        ]
        uow = self._uow(all_items=items)

        _conflict_service(uow).list_all_for_track(event_pk=1, track_pk=None)

        uow.sessions.read.assert_not_called()
        uow.sessions.read_facilitators.assert_not_called()
        uow.spaces.read.assert_not_called()
        uow.agenda_items.list_overlapping_in_space.assert_not_called()
        uow.sessions.read_participants_limits.assert_called_once()
        uow.sessions.read_facilitators_by_sessions.assert_called_once()

    def test_detect_for_assignment_reuses_the_batched_engine(self):
        own = _make_item(pk=1, session_id=10, space_id=1)
        other = _make_item(pk=2, session_id=20, space_id=1, session_title="Other")
        uow = self._uow(all_items=[own, other])

        conflicts = _conflict_service(uow).detect_for_assignment(
            event_pk=1, session_pk=10
        )

        assert [(c.type, c.session_pk) for c in conflicts] == [
            (ConflictType.SPACE_OVERLAP, 20)
        ]
        uow.sessions.read.assert_not_called()

    def test_detect_for_assignment_rejects_an_unscheduled_session(self):
        uow = self._uow(all_items=[_make_item(pk=1, session_id=10, space_id=1)])

        with pytest.raises(NotFoundError):
            _conflict_service(uow).detect_for_assignment(event_pk=1, session_pk=99)


class TestListPreferredSlotViolations:
    @staticmethod
    def _uow(*, items, preferred):
        uow = MagicMock()
        uow.agenda_items.list_by_event.return_value = items
        uow.agenda_items.list_by_track.return_value = items
        uow.sessions.read_preferred_time_slots_by_sessions.return_value = preferred
        uow.sessions.list_track_names_by_session.return_value = {}
        uow.tracks.read.return_value = _event_track(event_pk=1)
        uow.tracks.list_manager_names_by_tracks.return_value = {}
        return uow

    def test_session_inside_its_preferred_range_is_not_a_violation(self):
        item = _make_item(
            pk=1,
            session_id=10,
            start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
        )
        slot = _slot(
            datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
            datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        )
        uow = self._uow(items=[item], preferred={10: [slot]})

        violations = _conflict_service(uow).list_preferred_slot_violations(
            event_pk=1, track_pk=None
        )

        assert not violations

    def test_session_outside_its_preferred_range_carries_foreign_attribution(self):
        item = _make_item(
            pk=1,
            session_id=10,
            session_title="Evening quiz",
            start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
        )
        slot = _slot(
            datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
            datetime(2026, 1, 1, 13, 0, tzinfo=UTC),
        )
        uow = self._uow(items=[item], preferred={10: [slot]})
        uow.sessions.list_track_names_by_session.return_value = {10: {6: "Board games"}}
        uow.tracks.list_manager_names_by_tracks.return_value = {6: ["Basia"]}

        violations = _conflict_service(uow).list_preferred_slot_violations(
            event_pk=1, track_pk=5
        )

        assert len(violations) == 1
        violation = violations[0]
        assert violation.session_pk == _SUBJECT_SESSION_PK
        assert violation.session_title == "Evening quiz"
        assert violation.scheduled_start == item.start_time
        assert violation.scheduled_end == item.end_time
        assert [(r.start_time, r.end_time) for r in violation.preferred_slots] == [
            (slot.start_time, slot.end_time)
        ]
        assert violation.track_name == "Board games"
        assert violation.manager_names == ["Basia"]


class TestTrackProgress:
    def test_counts_come_from_one_aggregate(self):
        accepted, scheduled, pending, rejected = 4, 3, 2, 1
        uow = MagicMock()
        uow.tracks.list_by_event.return_value = [
            _track_stub(1, "RPG"),
            _track_stub(2, "Board games"),
        ]
        uow.sessions.count_by_track.return_value = {
            1: TrackSessionCountsDTO(
                pending=pending,
                accepted=accepted,
                scheduled=scheduled,
                rejected=rejected,
            )
        }
        uow.tracks.list_manager_names_by_tracks.return_value = {1: ["Ala"]}

        result = _overview_service(uow).track_progress(event_pk=1)

        assert result == [
            TrackProgressDTO(
                track_pk=1,
                track_name="RPG",
                manager_names=["Ala"],
                accepted_count=accepted,
                scheduled_count=scheduled,
                pending_count=pending,
                on_hold_count=0,
                rejected_count=rejected,
                progress_pct=50,
            ),
            TrackProgressDTO(
                track_pk=2,
                track_name="Board games",
                manager_names=[],
                accepted_count=0,
                scheduled_count=0,
                pending_count=0,
                on_hold_count=0,
                rejected_count=0,
                progress_pct=0,
            ),
        ]
        uow.tracks.list_by_event.assert_called_once_with(1)
        uow.sessions.count_by_track.assert_called_once_with(1)
        uow.tracks.list_manager_names_by_tracks.assert_called_once_with({1, 2})
        uow.sessions.list_sessions_by_event.assert_not_called()

    def test_on_hold_sessions_are_reported_but_not_counted_as_active(self):
        uow = MagicMock()
        uow.tracks.list_by_event.return_value = [_track_stub(1, "RPG")]
        uow.sessions.count_by_track.return_value = {
            1: TrackSessionCountsDTO(pending=1, accepted=2, scheduled=1, on_hold=5)
        }
        uow.tracks.list_manager_names_by_tracks.return_value = {}

        result = _overview_service(uow).track_progress(event_pk=1)

        assert result == [
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

    def test_no_tracks_short_circuits(self):
        uow = MagicMock()
        uow.tracks.list_by_event.return_value = []

        assert not _overview_service(uow).track_progress(event_pk=1)

        uow.sessions.count_by_track.assert_not_called()


class TestTimetableOverviewServiceDefaults:
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

    def test_build_heatmap_fetches_conflicts_when_none(self, mock_uow):
        svc = TimetableOverviewService(mock_uow)
        result = svc.build_heatmap(event_pk=1, tz=UTC, conflicts=None)

        assert result == HeatmapDTO(spaces=[], rows=[], days=[])
        mock_uow.time_slots.list_by_event.assert_called_once_with(1)
        # Conflict detection reads the spaces and the agenda too, once each.
        assert mock_uow.spaces.list_by_event.call_args_list == [call(1), call(1)]
        assert mock_uow.agenda_items.list_by_event.call_args_list == [call(1), call(1)]

    @pytest.mark.parametrize(
        ("slot_end", "row_times"),
        (
            (datetime(2026, 1, 1, 11, 0, tzinfo=UTC), [10]),
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

    def test_all_conflicts_grouped_fetches_conflicts_when_none(self, mock_uow):
        svc = TimetableOverviewService(mock_uow)
        result = svc.all_conflicts_grouped(event_pk=1, conflicts=None)

        assert result == {}
        mock_uow.agenda_items.list_by_event.assert_called_once_with(1)

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


def _space(pk, parent_id=None):
    return SpaceDTO(
        pk=pk,
        parent_id=parent_id,
        capacity=None,
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

    def test_capacity_is_rooms_times_slot_hours(self):
        slots = [
            _slot(
                datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
            ),
            _slot(
                datetime(2026, 1, 1, 14, 0, tzinfo=UTC),
                datetime(2026, 1, 1, 16, 0, tzinfo=UTC),
            ),
        ]
        uow = self._uow(spaces=[_space(1), _space(2)], slots=slots, items=[])

        result = _overview_service(uow).capacity_hours(event_pk=1)

        assert result == CapacityHoursDTO(
            room_count=2,
            slot_hours=4.0,
            capacity_hours=8.0,
            scheduled_hours=0.0,
            hours_to_fill=8.0,
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

    def test_partially_filled_subtracts_scheduled_hours(self):
        slots = [
            _slot(
                datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
            )
        ]
        items = [
            _make_item(
                space_id=1,
                start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                end_time=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
            )
        ]
        uow = self._uow(spaces=[_space(1), _space(2)], slots=slots, items=items)

        result = _overview_service(uow).capacity_hours(event_pk=1)

        assert result == CapacityHoursDTO(
            room_count=2,
            slot_hours=2.0,
            capacity_hours=4.0,
            scheduled_hours=1.0,
            hours_to_fill=3.0,
            filled_pct=25,
        )

    def test_fully_filled_leaves_nothing_and_hits_100_pct(self):
        slots = [
            _slot(
                datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
            )
        ]
        items = [
            _make_item(
                pk=1,
                space_id=1,
                start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                end_time=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
            )
        ]
        uow = self._uow(spaces=[_space(1)], slots=slots, items=items)

        result = _overview_service(uow).capacity_hours(event_pk=1)

        assert result == CapacityHoursDTO(
            room_count=1,
            slot_hours=2.0,
            capacity_hours=2.0,
            scheduled_hours=2.0,
            hours_to_fill=0.0,
            filled_pct=100,
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

    def test_items_in_other_rooms_are_ignored(self):
        slots = [
            _slot(
                datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
            )
        ]
        items = [
            _make_item(
                space_id=99,
                start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                end_time=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
            )
        ]
        uow = self._uow(spaces=[_space(1)], slots=slots, items=items)

        result = _overview_service(uow).capacity_hours(event_pk=1)

        assert result == CapacityHoursDTO(
            room_count=1,
            slot_hours=1.0,
            capacity_hours=1.0,
            scheduled_hours=0.0,
            hours_to_fill=1.0,
            filled_pct=0,
        )

    def test_odd_duration_slot_rounds_to_one_decimal(self):
        slots = [
            _slot(
                datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                datetime(2026, 1, 1, 11, 30, tzinfo=UTC),
            )
        ]
        uow = self._uow(spaces=[_space(1)], slots=slots, items=[])

        result = _overview_service(uow).capacity_hours(event_pk=1)

        assert result == CapacityHoursDTO(
            room_count=1,
            slot_hours=1.5,
            capacity_hours=1.5,
            scheduled_hours=0.0,
            hours_to_fill=1.5,
            filled_pct=0,
        )
