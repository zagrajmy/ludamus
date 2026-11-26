from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock, call

import pytest

from ludamus.pacts.availability import DayPart
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.sessions import SessionStatus
from ludamus.pacts.timetable import (
    PlacementRejectedError,
    PlacementRejection,
    ScheduleChangeAction,
    SessionPlacement,
    TimetableGridFilter,
)
from ludamus.pacts.venues import SpaceDTO
from tests.unit.factories import agenda_item_dto
from tests.unit.timetable_helpers import (
    START,
    FakeAgendaItems,
    event_stub,
    event_track,
    lookup,
    offered,
    space_dto,
    spec_uow,
    stub_warning_reads,
    subset,
    timetable_service,
)

UNASSIGN_LOG_PK = 77


class TestBuildGridOverlappingSessions:
    def test_overlapping_items_are_placed_side_by_side(self):
        uow = MagicMock()
        uow.events.read.return_value = event_stub(
            datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
            datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        )

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

        item_a = agenda_item_dto(
            pk=1,
            space_id=1,
            start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
        )
        item_b = agenda_item_dto(
            pk=2,
            space_id=1,
            start_time=datetime(2026, 1, 1, 10, 30, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, 11, 30, tzinfo=UTC),
        )
        item_c = agenda_item_dto(
            pk=3,
            space_id=1,
            start_time=datetime(2026, 1, 1, 11, 30, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        )
        uow.agenda_items.list_by_event.return_value = [item_a, item_b, item_c]

        svc = timetable_service(uow)
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
        uow = spec_uow(
            agenda_items=FakeAgendaItems(
                agenda_item_dto(
                    pk=1,
                    session_id=1,
                    start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                    end_time=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
                ),
                agenda_item_dto(
                    pk=2,
                    session_id=2,
                    start_time=datetime(2026, 1, 1, 10, 30, tzinfo=UTC),
                    end_time=datetime(2026, 1, 1, 11, 30, tzinfo=UTC),
                ),
                agenda_item_dto(
                    pk=3,
                    session_id=3,
                    start_time=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
                    end_time=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
                ),
            )
        )
        uow.spaces.list_by_event.side_effect = lookup({1: [space_dto(1)]})
        uow.events.read.side_effect = lookup(
            {1: event_stub(START, START + timedelta(hours=2))}
        )
        stub_warning_reads(uow)

        grid = timetable_service(uow).build_grid(event_pk=1, tz=UTC)

        sessions = grid.days[0].columns[0].sessions
        assert [pos.lane_width_pct for pos in sessions] == pytest.approx([100 / 3] * 3)
        assert [pos.lane_start_pct for pos in sessions] == pytest.approx(
            [0, 100 / 3, 200 / 3]
        )

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
        uow.tracks.list_space_pks.side_effect = lookup({5: [1]})
        uow.events.read.return_value = event_stub(
            datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
            datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        )
        mine = agenda_item_dto(
            pk=1,
            session_title="Mine",
            start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
        )
        theirs = agenda_item_dto(
            pk=2,
            session_id=2,
            session_title="Theirs",
            start_time=datetime(2026, 1, 1, 10, 30, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, 11, 30, tzinfo=UTC),
        )
        untracked = agenda_item_dto(
            pk=3,
            session_id=3,
            session_title="Untracked",
            start_time=datetime(2026, 1, 1, 11, 30, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        )
        uow.agenda_items.list_by_event.return_value = [mine, theirs, untracked]
        uow.agenda_items.list_by_track.return_value = [mine]
        uow.tracks.read.side_effect = lookup({5: event_track(event_pk=1)})
        stub_warning_reads(uow)
        uow.sessions.read_availability_by_sessions.side_effect = subset(
            {3: [offered(2, DayPart.MORNING)]}
        )

        grid = timetable_service(uow).build_grid(
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

    def test_invalid_date_falls_back_to_the_first_event_day(self):
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
        uow.events.read.return_value = event_stub(
            datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
            datetime(2026, 1, 2, 12, 0, tzinfo=UTC),
        )
        uow.agenda_items.list_by_event.return_value = []

        grid = timetable_service(uow).build_grid(
            event_pk=1,
            tz=UTC,
            filters=TimetableGridFilter(date_selection=date(2027, 1, 1)),
        )

        assert grid.date_selection == date(2026, 1, 1)
        assert [day.total_minutes for day in grid.days] == [2 * 60]

    def test_something_scheduled_overnight_adds_the_day_it_lands_on(self):
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
        uow.events.read.return_value = event_stub(
            datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
            datetime(2026, 1, 1, 22, 0, tzinfo=UTC),
        )
        night_owl = agenda_item_dto(
            start_time=datetime(2026, 1, 2, 0, 0, tzinfo=UTC),
            end_time=datetime(2026, 1, 2, 1, 0, tzinfo=UTC),
        )
        uow.agenda_items.list_by_event.return_value = [night_owl]

        grid = timetable_service(uow).build_grid(
            event_pk=1, tz=UTC, filters=TimetableGridFilter(date_selection="all")
        )

        assert grid.available_dates == [date(2026, 1, 1), date(2026, 1, 2)]
        day_one, day_two = grid.days
        assert [day.total_minutes for day in grid.days] == [22 * 60, 22 * 60]
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
        # An event that opens in the small hours and runs late covers the whole
        # clock, so both halves of a midnight session have a row to sit on.
        uow.events.read.return_value = event_stub(
            datetime(2026, 1, 1, 0, 30, tzinfo=UTC),
            datetime(2026, 1, 2, 22, 0, tzinfo=UTC),
        )
        night_owl = agenda_item_dto(
            start_time=datetime(2026, 1, 1, 22, 0, tzinfo=UTC),
            end_time=datetime(2026, 1, 2, 2, 0, tzinfo=UTC),
            session_duration_minutes=4 * 60,
        )
        uow.agenda_items.list_by_event.return_value = [night_owl]

        grid = timetable_service(uow).build_grid(
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


class TestGridExtendedHours:
    @staticmethod
    def _uow(start, end):
        uow = MagicMock()
        now = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
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
        uow.events.read.return_value = event_stub(start, end)
        uow.agenda_items.list_by_event.return_value = []
        return uow

    def test_the_grid_reports_the_room_page_it_is_showing(self):
        uow = self._uow(
            datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
            datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        )

        grid = timetable_service(uow).build_grid(event_pk=1, tz=UTC)

        assert (grid.first_space_number, grid.last_space_number) == (1, 1)
        assert (grid.extend_before_hours, grid.extend_after_hours) == (0, 0)
        assert grid.can_extend_before is True
        assert grid.can_extend_after is True

    def test_asking_for_extra_hours_widens_the_axis(self):
        uow = self._uow(
            datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
            datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        )

        grid = timetable_service(uow).build_grid(
            event_pk=1,
            tz=UTC,
            filters=TimetableGridFilter(extend_before_hours=2, extend_after_hours=1),
        )

        assert grid.days[0].total_minutes == 5 * 60
        assert grid.days[0].time_labels[0].time.strftime("%H:%M") == "08:00"
        assert (grid.extend_before_hours, grid.extend_after_hours) == (2, 1)

    def test_an_axis_already_at_the_edge_of_the_day_cannot_extend_further(self):
        uow = self._uow(
            datetime(2026, 1, 1, 0, 30, tzinfo=UTC),
            datetime(2026, 1, 1, 23, 30, tzinfo=UTC),
        )

        grid = timetable_service(uow).build_grid(event_pk=1, tz=UTC)

        assert grid.can_extend_before is False
        assert grid.can_extend_after is False


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
        uow.events.read.return_value = event_stub(
            datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
            datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        )
        uow.agenda_items.list_by_event.return_value = []
        return uow

    def test_grid_uses_programme_order_instead_of_tree_order(self, uow):
        by_pk = {space.pk: space for space in uow.spaces.list_by_event.return_value}
        by_pk[6].programme_order = 0
        by_pk[3].programme_order = 1
        by_pk[4].programme_order = 2

        grid = timetable_service(uow).build_grid(event_pk=1, tz=UTC)

        assert [space.pk for space in grid.spaces] == [6, 3, 4]


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
