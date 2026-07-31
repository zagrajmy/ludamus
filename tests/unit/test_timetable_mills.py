from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

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
from ludamus.pacts.chronology import CapacityHoursDTO, ConflictType, SessionPlacement


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
        # Overlapping items extend the lane group and share the column width.
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

        svc = TimetableService(uow)
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

        grid = TimetableService(uow).build_grid(
            event_pk=1, tz=UTC, date_selection="all"
        )

        expected_total_minutes = 180
        assert [day.date.isoformat() for day in grid.days] == [
            "2026-01-01",
            "2026-01-02",
        ]
        assert [day.columns[0].space.pk for day in grid.days] == [space.pk, space.pk]
        assert [
            day.columns[0].sessions[0].agenda_item.session_title for day in grid.days
        ] == ["Day one", "Day two"]
        assert grid.total_minutes == expected_total_minutes
        assert [label.time.strftime("%H:%M") for label in grid.time_labels] == [
            "10:00",
            "11:00",
            "12:00",
            "13:00",
        ]
        assert [day.columns[0].sessions[0].start_minutes for day in grid.days] == [
            0,
            60,
        ]
        assert grid.date_selection == "all"
        uow.agenda_items.list_by_event.assert_called_once_with(1)

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

        grid = TimetableService(uow).build_grid(
            event_pk=1, tz=UTC, date_selection=date(2027, 1, 1)
        )

        assert grid.date_selection == date(2026, 1, 1)
        assert grid.total_minutes == 4 * 60

    def test_overnight_slot_extends_its_day_instead_of_adding_a_24h_day(self):
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

        grid = TimetableService(uow).build_grid(
            event_pk=1, tz=UTC, date_selection="all"
        )

        assert grid.available_dates == [date(2026, 1, 1), date(2026, 1, 2)]
        assert grid.total_minutes == 13 * 60
        assert [label.time.strftime("%H:%M") for label in grid.time_labels][:2] == [
            "12:00",
            "13:00",
        ]
        assert grid.time_labels[-1].time.strftime("%H:%M") == "01:00"
        day_one, day_two = grid.days
        assert [pos.start_minutes for pos in day_one.columns[0].sessions] == [12 * 60]
        assert day_two.columns[0].sessions == []

    def test_overlapping_day_ranges_render_each_item_in_exactly_one_column(self):
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
                start_time=datetime(2026, 1, 1, 18, 0, tzinfo=UTC),
                end_time=datetime(2026, 1, 2, 1, 0, tzinfo=UTC),
            ),
            TimeSlotDTO(
                pk=2,
                start_time=datetime(2026, 1, 2, 0, 30, tzinfo=UTC),
                end_time=datetime(2026, 1, 2, 2, 0, tzinfo=UTC),
            ),
        ]
        first_night = _make_item(
            pk=1,
            start_time=datetime(2026, 1, 2, 0, 15, tzinfo=UTC),
            end_time=datetime(2026, 1, 2, 0, 30, tzinfo=UTC),
        )
        second_night = _make_item(
            pk=2,
            session_id=2,
            start_time=datetime(2026, 1, 2, 0, 30, tzinfo=UTC),
            end_time=datetime(2026, 1, 2, 1, 30, tzinfo=UTC),
        )
        uow.agenda_items.list_by_event.return_value = [first_night, second_night]

        grid = TimetableService(uow).build_grid(
            event_pk=1, tz=UTC, date_selection="all"
        )

        day_one, day_two = grid.days
        # Day one's range reaches 01:00 of Jan 2 while day two's starts at
        # midnight (00:30 floored to the hour grid), so both contain the two
        # night items; the later day owns the overlap instead of rendering
        # the items in both columns.
        assert day_one.columns[0].sessions == []
        assert [
            (pos.agenda_item.pk, pos.start_minutes)
            for pos in day_two.columns[0].sessions
        ] == [(1, 15), (2, 30)]


class TestRevertChange:
    @pytest.fixture
    def mock_uow(self):
        uow = MagicMock()
        # By default the log under test (pk 1, session 1) is the latest change.
        uow.schedule_change_logs.latest_pk_for_session.return_value = 1
        return uow

    @pytest.fixture
    def service(self, mock_uow):
        return TimetableService(mock_uow)

    def test_revert_rejects_non_latest_change(self, service, mock_uow):
        # Only the most recent change for a session may be reverted.
        log = MagicMock()
        log.event_id = 1
        log.action = ScheduleChangeAction.ASSIGN
        log.session_id = 1
        mock_uow.schedule_change_logs.read.return_value = log
        # A newer change (pk 2) exists for the same session.
        mock_uow.schedule_change_logs.latest_pk_for_session.return_value = 2

        with pytest.raises(ValueError, match="latest change"):
            service.revert_change(log_pk=1, event_pk=1)

        mock_uow.agenda_items.read_by_session.assert_not_called()

    def test_revert_raises_not_found_for_log_from_another_event(
        self, service, mock_uow
    ):
        # A log belonging to another event is rejected before reverting.
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
        # Reverting an ASSIGN whose agenda item is already gone is a no-op delete.
        log = MagicMock()
        log.event_id = 1
        log.action = ScheduleChangeAction.ASSIGN
        log.session_id = 1
        mock_uow.schedule_change_logs.read.return_value = log
        mock_uow.agenda_items.read_by_session.return_value = None

        with pytest.raises(NotFoundError):
            service.revert_change(log_pk=1, event_pk=1)

    def test_revert_unassign_raises_when_missing_placement_data(
        self, service, mock_uow
    ):
        # An UNASSIGN log without its original placement cannot be reverted.
        log = MagicMock()
        log.event_id = 1
        log.action = ScheduleChangeAction.UNASSIGN
        log.session_id = 1
        log.old_space_id = None
        log.old_start_time = None
        log.old_end_time = None
        mock_uow.schedule_change_logs.read.return_value = log

        with pytest.raises(ValueError, match="missing original placement data"):
            service.revert_change(log_pk=1, event_pk=1)

    def test_revert_unassign_raises_when_session_not_accepted(self, service, mock_uow):
        # The session must still be ACCEPTED to revert an unassign.
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

        with pytest.raises(ValueError, match="is not in ACCEPTED status"):
            service.revert_change(log_pk=1, event_pk=1)

    def test_revert_unassign_restores_the_original_placement(self, service, mock_uow):
        log = MagicMock()
        log.event_id = 1
        log.action = ScheduleChangeAction.UNASSIGN
        log.session_id = 1
        log.old_space_id = 5
        log.old_start_time = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        log.old_end_time = datetime(2026, 1, 1, 11, 0, tzinfo=UTC)
        mock_uow.schedule_change_logs.read.return_value = log
        mock_uow.sessions.read.return_value.status = SessionStatus.ACCEPTED
        mock_uow.sessions.read_event.return_value.pk = 1

        service.revert_change(log_pk=1, event_pk=1, user_pk=9)

        mock_uow.agenda_items.create.assert_called_once_with(
            {
                "session_id": 1,
                "space_id": 5,
                "start_time": log.old_start_time,
                "end_time": log.old_end_time,
                "session_confirmed": False,
            }
        )
        mock_uow.schedule_change_logs.create.assert_called_once_with(
            {
                "event_id": 1,
                "session_id": 1,
                "user_id": 9,
                "action": ScheduleChangeAction.REVERT,
                "new_space_id": 5,
                "new_start_time": log.old_start_time,
                "new_end_time": log.old_end_time,
            }
        )

    def test_revert_unknown_action_raises(self, service, mock_uow):
        # An unknown action type is rejected instead of guessed at.
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
        return TimetableService(mock_uow)

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

    def _arrange_acceptable_assignment(self, mock_uow, *, auto_confirm_sessions):
        mock_uow.sessions.read_event.return_value = self._event(
            1, auto_confirm_sessions=auto_confirm_sessions
        )
        space = MagicMock()
        space.pk = 1
        space.parent_id = None  # a childless root is a leaf (a bookable room)
        mock_uow.spaces.list_by_event.return_value = [space]
        mock_uow.agenda_items.read_by_session.return_value = None
        session = MagicMock()
        session.status = SessionStatus.ACCEPTED
        mock_uow.sessions.read.return_value = session

    def test_assign_confirms_when_event_auto_confirms(self, service, mock_uow):
        self._arrange_acceptable_assignment(mock_uow, auto_confirm_sessions=True)

        service.assign_session(session_pk=1, placement=self._placement(), event_pk=1)

        created = mock_uow.agenda_items.create.call_args.args[0]
        assert created["session_confirmed"] is True

    def test_assign_leaves_unconfirmed_when_event_disables_auto_confirm(
        self, service, mock_uow
    ):
        self._arrange_acceptable_assignment(mock_uow, auto_confirm_sessions=False)

        service.assign_session(session_pk=1, placement=self._placement(), event_pk=1)

        created = mock_uow.agenda_items.create.call_args.args[0]
        assert created["session_confirmed"] is False

    def test_move_unconfirms_even_when_event_auto_confirms(self, service, mock_uow):
        self._arrange_acceptable_assignment(mock_uow, auto_confirm_sessions=True)
        # An existing agenda item means this assignment is a move.
        mock_uow.agenda_items.read_by_session.return_value = MagicMock()

        service.assign_session(session_pk=1, placement=self._placement(), event_pk=1)

        created = mock_uow.agenda_items.create.call_args.args[0]
        assert created["session_confirmed"] is False


def _facilitator(pk, display_name="Alice"):
    facilitator = MagicMock()
    facilitator.pk = pk
    facilitator.display_name = display_name
    return facilitator


def _track_stub(pk, name="Track"):
    track = MagicMock()
    track.pk = pk
    track.name = name
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
        # Detection indexes limits directly, so the default covers every item.
        uow.sessions.read_participants_limits.return_value = (
            limits if limits is not None else {i.session_id: 0 for i in all_items}
        )
        uow.sessions.read_facilitators_by_sessions.return_value = facilitators or {}
        uow.tracks.list_by_sessions.return_value = {}
        uow.tracks.list_manager_names_by_tracks.return_value = {}
        return uow

    def test_space_overlap_detected_and_deduplicated(self):
        first = _make_item(pk=1, session_id=10, space_id=1, session_title="First")
        second = _make_item(pk=2, session_id=20, space_id=1, session_title="Second")
        uow = self._uow(all_items=[first, second])

        conflicts = ConflictDetectionService(uow).list_all_for_track(
            event_pk=1, track_pk=None
        )

        # One conflict for the pair, not one per direction.
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

        conflicts = ConflictDetectionService(uow).list_all_for_track(
            event_pk=1, track_pk=None
        )

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

        conflicts = ConflictDetectionService(uow).list_all_for_track(
            event_pk=1, track_pk=None
        )

        assert len(conflicts) == 1
        assert conflicts[0].type == ConflictType.CAPACITY_EXCEEDED
        assert conflicts[0].space_capacity == _ROOM_CAPACITY
        assert conflicts[0].session_limit == _SESSION_LIMIT

    def test_facilitator_overlap_across_tracks_gets_attribution(self):
        subject = _make_item(pk=1, session_id=10, space_id=1)
        other = _make_item(pk=2, session_id=20, space_id=2, session_title="Other")
        shared = _facilitator(7)
        uow = self._uow(
            all_items=[subject, other],
            subjects=[subject],
            facilitators={10: [shared], 20: [shared]},
        )
        uow.tracks.list_by_sessions.return_value = {20: [_track_stub(6, "Board games")]}
        uow.tracks.list_manager_names_by_tracks.return_value = {6: ["Basia"]}

        conflicts = ConflictDetectionService(uow).list_all_for_track(
            event_pk=1, track_pk=5
        )

        assert len(conflicts) == 1
        conflict = conflicts[0]
        assert conflict.type == ConflictType.FACILITATOR_OVERLAP
        assert conflict.facilitator_name == "Alice"
        assert conflict.track_name == "Board games"
        assert conflict.manager_names == ["Basia"]
        uow.tracks.list_by_sessions.assert_called_once_with({20})
        uow.tracks.list_manager_names_by_tracks.assert_called_once_with({6})

    def test_no_other_tracks_returns_conflict_unchanged(self):
        # Attribution filtering removes the current track, leaving nothing to
        # attribute the clash to.
        current_track_pk = 5
        subject = _make_item(pk=1, session_id=10, space_id=1)
        other = _make_item(pk=2, session_id=20, space_id=2, session_title="Other")
        shared = _facilitator(7)
        uow = self._uow(
            all_items=[subject, other],
            subjects=[subject],
            facilitators={10: [shared], 20: [shared]},
        )
        uow.tracks.list_by_sessions.return_value = {20: [_track_stub(current_track_pk)]}

        conflicts = ConflictDetectionService(uow).list_all_for_track(
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

        ConflictDetectionService(uow).list_all_for_track(event_pk=1, track_pk=None)

        uow.sessions.read.assert_not_called()
        uow.sessions.read_facilitators.assert_not_called()
        uow.spaces.read.assert_not_called()
        uow.agenda_items.list_overlapping_in_space.assert_not_called()
        uow.sessions.read_participants_limits.assert_called_once()
        uow.sessions.read_facilitators_by_sessions.assert_called_once()

    def test_detect_for_assignment_reuses_the_batched_engine(self):
        # Runs post-commit: the session's own agenda item is in the context,
        # self-excludes, and still clashes with another session in the space.
        own = _make_item(pk=1, session_id=10, space_id=1)
        other = _make_item(pk=2, session_id=20, space_id=1, session_title="Other")
        uow = self._uow(all_items=[own, other])

        conflicts = ConflictDetectionService(uow).detect_for_assignment(
            event_pk=1, session_pk=10
        )

        assert [(c.type, c.session_pk) for c in conflicts] == [
            (ConflictType.SPACE_OVERLAP, 20)
        ]
        uow.sessions.read.assert_not_called()

    def test_detect_for_assignment_rejects_an_unscheduled_session(self):
        uow = self._uow(all_items=[_make_item(pk=1, session_id=10, space_id=1)])

        with pytest.raises(NotFoundError):
            ConflictDetectionService(uow).detect_for_assignment(
                event_pk=1, session_pk=99
            )


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

        result = TimetableOverviewService(uow).track_progress(event_pk=1)

        assert [r.track_pk for r in result] == [1, 2]
        first = result[0]
        assert first.accepted_count == accepted
        assert first.scheduled_count == scheduled
        assert first.pending_count == pending
        assert first.rejected_count == rejected
        assert first.on_hold_count == 0
        assert first.progress_pct == round(scheduled * 100 / (pending + accepted))
        assert first.manager_names == ["Ala"]
        second = result[1]
        assert second.accepted_count == 0
        assert second.progress_pct == 0
        assert second.manager_names == []
        uow.sessions.list_sessions_by_event.assert_not_called()

    def test_no_tracks_short_circuits(self):
        uow = MagicMock()
        uow.tracks.list_by_event.return_value = []

        assert not TimetableOverviewService(uow).track_progress(event_pk=1)

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
        # conflicts=None makes build_heatmap fetch conflicts itself.
        svc = TimetableOverviewService(mock_uow)
        result = svc.build_heatmap(event_pk=1, tz=UTC, conflicts=None)

        assert result.spaces == []
        assert not result.days

    def test_all_conflicts_grouped_fetches_conflicts_when_none(self, mock_uow):
        # conflicts=None makes all_conflicts_grouped fetch conflicts itself.
        svc = TimetableOverviewService(mock_uow)
        result = svc.all_conflicts_grouped(event_pk=1, conflicts=None)

        assert not result


def _space(pk, parent_id=None):
    return SimpleNamespace(pk=pk, parent_id=parent_id)


def _slot(start, end):
    return SimpleNamespace(start_time=start, end_time=end)


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

        result = TimetableOverviewService(uow).capacity_hours(event_pk=1)

        assert result == CapacityHoursDTO(
            room_count=0,
            slot_hours=0.0,
            capacity_hours=0.0,
            scheduled_hours=0.0,
            hours_to_fill=0.0,
            filled_pct=0,
        )

    def test_capacity_is_rooms_times_slot_hours(self):
        # 2 rooms, two 2h slots => 2 * 4h = 8h capacity, nothing scheduled.
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

        result = TimetableOverviewService(uow).capacity_hours(event_pk=1)

        assert result == CapacityHoursDTO(
            room_count=2,
            slot_hours=4.0,
            capacity_hours=8.0,
            scheduled_hours=0.0,
            hours_to_fill=8.0,
            filled_pct=0,
        )

    def test_branch_spaces_are_not_bookable_rooms(self):
        # A venue node with two rooms under it: only the leaves count, or the
        # un-bookable branch would inflate capacity.
        slots = [
            _slot(
                datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
            )
        ]
        spaces = [_space(1), _space(2, parent_id=1), _space(3, parent_id=1)]
        uow = self._uow(spaces=spaces, slots=slots, items=[])

        result = TimetableOverviewService(uow).capacity_hours(event_pk=1)

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
        # 2 rooms * 2h = 4h capacity; one 1h item scheduled => 3h left, 25%.
        items = [
            _make_item(
                space_id=1,
                start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                end_time=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
            )
        ]
        uow = self._uow(spaces=[_space(1), _space(2)], slots=slots, items=items)

        result = TimetableOverviewService(uow).capacity_hours(event_pk=1)

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

        result = TimetableOverviewService(uow).capacity_hours(event_pk=1)

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
        # 1 room * 1h = 1h capacity, but a 2h item is scheduled in it.
        items = [
            _make_item(
                space_id=1,
                start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                end_time=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
            )
        ]
        uow = self._uow(spaces=[_space(1)], slots=slots, items=items)

        result = TimetableOverviewService(uow).capacity_hours(event_pk=1)

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
        # Only room 1 belongs to the event; the item sits in room 99.
        items = [
            _make_item(
                space_id=99,
                start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                end_time=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
            )
        ]
        uow = self._uow(spaces=[_space(1)], slots=slots, items=items)

        result = TimetableOverviewService(uow).capacity_hours(event_pk=1)

        assert result == CapacityHoursDTO(
            room_count=1,
            slot_hours=1.0,
            capacity_hours=1.0,
            scheduled_hours=0.0,
            hours_to_fill=1.0,
            filled_pct=0,
        )

    def test_odd_duration_slot_rounds_to_one_decimal(self):
        # 90-minute slot => 1.5h; one room, nothing scheduled.
        slots = [
            _slot(
                datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                datetime(2026, 1, 1, 11, 30, tzinfo=UTC),
            )
        ]
        uow = self._uow(spaces=[_space(1)], slots=slots, items=[])

        result = TimetableOverviewService(uow).capacity_hours(event_pk=1)

        assert result == CapacityHoursDTO(
            room_count=1,
            slot_hours=1.5,
            capacity_hours=1.5,
            scheduled_hours=0.0,
            hours_to_fill=1.5,
            filled_pct=0,
        )
