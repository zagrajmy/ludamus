from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from ludamus.mills.chronology import (
    ConflictDetectionService,
    TimetableOverviewService,
    TimetableService,
)
from ludamus.pacts import (
    AgendaItemDTO,
    AreaDTO,
    NotFoundError,
    ScheduleChangeAction,
    SessionStatus,
    SpaceDTO,
    TimeSlotDTO,
    VenueDTO,
)
from ludamus.pacts.chronology import ConflictType


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
        """Lines 56-57: overlapping items extend the group."""
        uow = MagicMock()
        event = MagicMock()
        event.start_time = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        event.end_time = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        uow.events.read.return_value = event

        now = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        venue = VenueDTO(
            address="",
            areas_count=1,
            creation_time=now,
            modification_time=now,
            name="Venue 1",
            order=0,
            pk=1,
            slug="venue-1",
        )
        area = AreaDTO(
            creation_time=now,
            description="",
            modification_time=now,
            name="Area 1",
            order=0,
            pk=1,
            slug="area-1",
            spaces_count=1,
            venue_id=1,
        )
        space = SpaceDTO(
            area_id=1,
            capacity=None,
            creation_time=now,
            modification_time=now,
            name="Room 1",
            order=0,
            pk=1,
            slug="room-1",
        )
        uow.spaces.list_by_event.return_value = [space]
        uow.venues.list_by_event.return_value = [venue]
        uow.areas.list_by_venue.return_value = [area]
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
        uow.agenda_items.list_by_event.return_value = [item_a, item_b]

        svc = TimetableService(uow)
        grid = svc.build_grid(event_pk=1, tz=UTC)

        sessions = grid.columns[0].sessions
        expected_count = 2
        expected_half_width = 50.0
        assert len(sessions) == expected_count
        assert sessions[0].lane_width_pct == pytest.approx(expected_half_width)
        assert sessions[1].lane_width_pct == pytest.approx(expected_half_width)
        assert sessions[0].lane_start_pct == pytest.approx(0.0)
        assert sessions[1].lane_start_pct == pytest.approx(expected_half_width)


class TestRevertChange:
    @pytest.fixture
    def mock_uow(self):
        return MagicMock()

    @pytest.fixture
    def service(self, mock_uow):
        return TimetableService(mock_uow)

    def test_revert_assign_raises_not_found_when_no_agenda_item(
        self, service, mock_uow
    ):
        """Line 210: agenda_item is None when reverting ASSIGN."""
        log = MagicMock()
        log.action = ScheduleChangeAction.ASSIGN
        log.event_id = 1
        log.session_id = 1
        mock_uow.schedule_change_logs.read.return_value = log
        mock_uow.agenda_items.read_by_session.return_value = None

        with pytest.raises(NotFoundError):
            service.revert_change(event_pk=1, log_pk=1)

    def test_revert_unassign_raises_when_missing_placement_data(
        self, service, mock_uow
    ):
        """Lines 221-222: missing original placement data."""
        log = MagicMock()
        log.action = ScheduleChangeAction.UNASSIGN
        log.event_id = 1
        log.session_id = 1
        log.old_space_id = None
        log.old_start_time = None
        log.old_end_time = None
        mock_uow.schedule_change_logs.read.return_value = log

        with pytest.raises(ValueError, match="missing original placement data"):
            service.revert_change(event_pk=1, log_pk=1)

    def test_revert_unassign_raises_when_session_not_pending(self, service, mock_uow):
        """Session must be in PENDING status to revert an unassign."""
        log = MagicMock()
        log.action = ScheduleChangeAction.UNASSIGN
        log.event_id = 1
        log.session_id = 1
        log.old_space_id = 5
        log.old_start_time = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        log.old_end_time = datetime(2026, 1, 1, 11, 0, tzinfo=UTC)
        mock_uow.schedule_change_logs.read.return_value = log

        session = MagicMock()
        session.status = SessionStatus.SCHEDULED
        mock_uow.sessions.read.return_value = session

        with pytest.raises(ValueError, match="is not in PENDING status"):
            service.revert_change(event_pk=1, log_pk=1)

    def test_revert_unknown_action_raises(self, service, mock_uow):
        """Lines 240-241: unknown action type."""
        log = MagicMock()
        log.action = "UNKNOWN_ACTION"
        log.event_id = 1
        log.session_id = 1
        mock_uow.schedule_change_logs.read.return_value = log

        with pytest.raises(ValueError, match="Cannot revert action"):
            service.revert_change(event_pk=1, log_pk=1)

    def test_revert_rejects_log_from_another_event(self, service, mock_uow):
        log = MagicMock()
        log.event_id = 2
        mock_uow.schedule_change_logs.read.return_value = log

        with pytest.raises(NotFoundError):
            service.revert_change(event_pk=1, log_pk=1)


class TestListAllForTrackAttribution:
    def test_no_other_tracks_returns_conflict_unchanged(self):
        """Lines 351, 353: filtering removes current track, leaving empty list."""
        uow = MagicMock()
        current_track_pk = 5

        item = _make_item(
            pk=1,
            session_id=10,
            space_id=1,
            start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
        )
        uow.agenda_items.list_by_track.return_value = [item]

        session = MagicMock()
        session.participants_limit = 5
        uow.sessions.read.return_value = session

        space = MagicMock()
        space.capacity = None
        uow.spaces.read.return_value = space

        facilitator = MagicMock()
        facilitator.pk = 1
        facilitator.display_name = "Alice"
        uow.sessions.read_facilitators.return_value = [facilitator]

        overlap_item = _make_item(
            pk=2,
            session_id=20,
            space_id=1,
            session_title="Other",
            start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
        )
        uow.agenda_items.list_overlapping_in_space.return_value = []
        uow.agenda_items.list_overlapping_by_facilitator.return_value = [overlap_item]

        track = MagicMock()
        track.pk = current_track_pk
        uow.tracks.list_by_session.return_value = [track]

        svc = ConflictDetectionService(uow)
        conflicts = svc.list_all_for_track(event_pk=1, track_pk=current_track_pk)

        facilitator_conflicts = [
            c for c in conflicts if c.type == ConflictType.FACILITATOR_OVERLAP
        ]
        assert len(facilitator_conflicts) > 0
        for conflict in facilitator_conflicts:
            assert conflict.track_name is None
            assert conflict.manager_names == []


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
        """Line 382: conflicts=None triggers self.get_all_conflicts."""
        svc = TimetableOverviewService(mock_uow)
        result = svc.build_heatmap(event_pk=1, tz=UTC, conflicts=None)

        assert result.spaces == []
        assert not result.days

    def test_all_conflicts_grouped_fetches_conflicts_when_none(self, mock_uow):
        """Line 423: conflicts=None triggers self.get_all_conflicts."""
        svc = TimetableOverviewService(mock_uow)
        result = svc.all_conflicts_grouped(event_pk=1, conflicts=None)

        assert not result
