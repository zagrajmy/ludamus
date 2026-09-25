from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from ludamus.mills.timetable import (
    ConflictDetectionService,
    TimetableOverviewService,
    TimetableService,
)
from ludamus.pacts import (
    AgendaItemDTO,
    ScheduleChangeAction,
    SessionStatus,
    SpaceDTO,
    TimeSlotDTO,
)
from ludamus.pacts.chronology import (
    CapacityHoursDTO,
    ConflictDTO,
    ConflictSeverity,
    ConflictType,
    HeatmapCellStatus,
    SessionPlacement,
    TimetableGridFilter,
)
from ludamus.pacts.timetable import (
    PlacementRejectedError,
    PlacementRejection,
    TimetableRepos,
)


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
        mock_uow.agenda_items.create.assert_not_called()


class TestAssignSession:
    @pytest.fixture
    def mock_uow(self):
        return MagicMock()

    @pytest.fixture
    def service(self, mock_uow):
        return _timetable_service(mock_uow)

    @staticmethod
    def _placement():
        return SessionPlacement(
            space_pk=1,
            start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
        )

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

    def test_assign_rejects_naive_datetimes(self, service, mock_uow):
        placement = self._placement()
        naive = SessionPlacement(
            space_pk=placement.space_pk,
            start_time=placement.start_time.replace(tzinfo=None),
            end_time=placement.end_time.replace(tzinfo=None),
        )

        with pytest.raises(PlacementRejectedError, match="must include a timezone"):
            service.assign_session(session_pk=1, placement=naive, event_pk=1)

        mock_uow.agenda_items.create.assert_not_called()

    def test_assign_rejects_an_inverted_time_range(self, service, mock_uow):
        placement = self._placement()
        inverted = SessionPlacement(
            space_pk=placement.space_pk,
            start_time=placement.end_time,
            end_time=placement.start_time,
        )

        with pytest.raises(PlacementRejectedError, match="end_time must be after"):
            service.assign_session(session_pk=1, placement=inverted, event_pk=1)

        mock_uow.agenda_items.create.assert_not_called()

    def test_move_unconfirms_even_when_event_auto_confirms(self, service, mock_uow):
        self._arrange_acceptable_assignment(mock_uow)
        mock_uow.agenda_items.read_by_session.return_value = MagicMock()

        service.assign_session(session_pk=1, placement=self._placement(), event_pk=1)

        created = mock_uow.agenda_items.create.call_args.args[0]
        assert created["session_confirmed"] is False

    def test_move_records_the_row_it_left(self, service, mock_uow):
        self._arrange_acceptable_assignment(mock_uow)
        mock_uow.agenda_items.read_by_session.return_value = MagicMock()
        unassign_log_pk = 77
        mock_uow.schedule_change_logs.create.return_value = unassign_log_pk

        service.assign_session(session_pk=1, placement=self._placement(), event_pk=1)

        assign_log = mock_uow.schedule_change_logs.create.call_args.args[0]
        assert assign_log["moved_from_id"] == unassign_log_pk


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
