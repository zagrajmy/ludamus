from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from ludamus.mills.chronology import (
    ConflictDetectionService,
    EventIntegrationsService,
    IntegrationImplementationNotFoundError,
    SessionConfirmationService,
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
from ludamus.pacts.chronology import (
    CapacityHoursDTO,
    CheckOutcome,
    CheckResult,
    ConflictType,
    EventIntegrationCreateData,
    IntegrationCheckRequest,
    IntegrationImplementationId,
    IntegrationKind,
    SessionPlacement,
)


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
        uow = MagicMock()
        # By default the log under test (pk 1, session 1) is the latest change.
        uow.schedule_change_logs.latest_pk_for_session.return_value = 1
        return uow

    @pytest.fixture
    def service(self, mock_uow):
        return TimetableService(mock_uow)

    def test_revert_rejects_non_latest_change(self, service, mock_uow):
        """Only the most recent change for a session may be reverted."""
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
        """A log belonging to another event is rejected before reverting."""
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
        """Line 210: agenda_item is None when reverting ASSIGN."""
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
        """Lines 221-222: missing original placement data."""
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

    def test_revert_unassign_raises_when_session_not_pending(self, service, mock_uow):
        """Session must be in PENDING status to revert an unassign."""
        log = MagicMock()
        log.event_id = 1
        log.action = ScheduleChangeAction.UNASSIGN
        log.session_id = 1
        log.old_space_id = 5
        log.old_start_time = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        log.old_end_time = datetime(2026, 1, 1, 11, 0, tzinfo=UTC)
        mock_uow.schedule_change_logs.read.return_value = log

        session = MagicMock()
        session.status = SessionStatus.SCHEDULED
        mock_uow.sessions.read.return_value = session

        with pytest.raises(ValueError, match="is not in PENDING status"):
            service.revert_change(log_pk=1, event_pk=1)

    def test_revert_unknown_action_raises(self, service, mock_uow):
        """Lines 240-241: unknown action type."""
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

    def _arrange_pending_assignment(self, mock_uow, *, auto_confirm_sessions):
        mock_uow.sessions.read_event.return_value = self._event(
            1, auto_confirm_sessions=auto_confirm_sessions
        )
        space = MagicMock()
        space.pk = 1
        mock_uow.spaces.list_by_event.return_value = [space]
        mock_uow.agenda_items.read_by_session.return_value = None
        session = MagicMock()
        session.status = SessionStatus.PENDING
        mock_uow.sessions.read.return_value = session

    def test_assign_confirms_when_event_auto_confirms(self, service, mock_uow):
        self._arrange_pending_assignment(mock_uow, auto_confirm_sessions=True)

        service.assign_session(session_pk=1, placement=self._placement(), event_pk=1)

        created = mock_uow.agenda_items.create.call_args.args[0]
        assert created["session_confirmed"] is True

    def test_assign_leaves_unconfirmed_when_event_disables_auto_confirm(
        self, service, mock_uow
    ):
        self._arrange_pending_assignment(mock_uow, auto_confirm_sessions=False)

        service.assign_session(session_pk=1, placement=self._placement(), event_pk=1)

        created = mock_uow.agenda_items.create.call_args.args[0]
        assert created["session_confirmed"] is False


class TestSessionConfirmation:
    """The service toggles confirmation and rejects foreign agenda items."""

    @pytest.fixture
    def agenda_items(self):
        return MagicMock()

    @pytest.fixture
    def sessions(self):
        return MagicMock()

    @pytest.fixture
    def tracks(self):
        return MagicMock()

    @pytest.fixture
    def transaction(self):
        transaction = MagicMock()
        transaction.atomic.return_value.__enter__.return_value = None
        return transaction

    @pytest.fixture
    def service(self, transaction, agenda_items, sessions, tracks):
        return SessionConfirmationService(transaction, agenda_items, sessions, tracks)

    @staticmethod
    def _event(pk):
        event = MagicMock()
        event.pk = pk
        return event

    @staticmethod
    def _track(event_id):
        track = MagicMock()
        track.event_id = event_id
        return track

    def test_confirm_persists_true(self, service, agenda_items, sessions):
        agenda_items.read.return_value = _make_item(pk=7, session_id=3)
        sessions.read_event.return_value = self._event(1)

        service.set_session_confirmed(event_pk=1, agenda_item_pk=7, confirmed=True)

        agenda_items.update.assert_called_once_with(7, {"session_confirmed": True})

    def test_unconfirm_persists_false(self, service, agenda_items, sessions):
        agenda_items.read.return_value = _make_item(pk=7, session_id=3)
        sessions.read_event.return_value = self._event(1)

        service.set_session_confirmed(event_pk=1, agenda_item_pk=7, confirmed=False)

        agenda_items.update.assert_called_once_with(7, {"session_confirmed": False})

    def test_rejects_agenda_item_from_another_event(
        self, service, agenda_items, sessions
    ):
        agenda_items.read.return_value = _make_item(pk=7, session_id=3)
        sessions.read_event.return_value = self._event(2)

        with pytest.raises(NotFoundError):
            service.set_session_confirmed(event_pk=1, agenda_item_pk=7, confirmed=True)

        agenda_items.update.assert_not_called()

    def test_confirm_all_confirms_every_item_in_event(self, service, agenda_items):
        service.confirm_all(event_pk=1)

        agenda_items.confirm_all_by_event.assert_called_once_with(1)

    def test_confirm_block_confirms_items_in_track(self, service, agenda_items, tracks):
        tracks.read.return_value = self._track(event_id=1)

        service.confirm_block(event_pk=1, track_pk=5)

        agenda_items.confirm_all_by_track.assert_called_once_with(5)

    def test_confirm_block_rejects_track_from_another_event(
        self, service, agenda_items, tracks
    ):
        tracks.read.return_value = self._track(event_id=2)

        with pytest.raises(NotFoundError):
            service.confirm_block(event_pk=1, track_pk=5)

        agenda_items.confirm_all_by_track.assert_not_called()


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


def _space(pk):
    return SimpleNamespace(pk=pk)


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

        assert result.room_count == 1 + 1  # East Wing + Fireside
        assert result.slot_hours == 2.0 + 2.0
        assert result.capacity_hours == 8.0
        assert result.scheduled_hours == 0.0
        assert result.hours_to_fill == 8.0
        assert result.filled_pct == 0

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

        assert result.capacity_hours == 4.0
        assert result.scheduled_hours == 1.0
        assert result.hours_to_fill == 3.0
        assert result.filled_pct == 25

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

        assert result.capacity_hours == 2.0
        assert result.scheduled_hours == 2.0
        assert result.hours_to_fill == 0.0
        assert result.filled_pct == 100

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

        assert result.hours_to_fill == 0.0
        assert result.filled_pct == 200

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

        assert result.scheduled_hours == 0.0
        assert result.hours_to_fill == 1.0

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

        assert result.slot_hours == 1.5
        assert result.capacity_hours == 1.5
        assert result.hours_to_fill == 1.5


# --- EventIntegrationsService ---


class _StrictConfig(BaseModel):
    endpoint: str


class _ImportStubImpl:
    kind = IntegrationKind.IMPORT
    config_model = _StrictConfig

    def check(self, secret, config):  # noqa: ARG002 - protocol shape
        return CheckResult(outcome=CheckOutcome.OK, hint="")


class _TicketingStubImpl:
    kind = IntegrationKind.TICKETING
    config_model = BaseModel

    def check(self, secret, config):  # noqa: ARG002 - protocol shape
        return CheckResult(outcome=CheckOutcome.OK, hint="")


_IMPL = IntegrationImplementationId.GOOGLE_PROPOSAL_PULLER


def _make_service(registry):
    transaction = MagicMock()
    transaction.atomic.return_value.__enter__ = MagicMock(return_value=None)
    transaction.atomic.return_value.__exit__ = MagicMock(return_value=None)
    integrations = MagicMock()
    connections = MagicMock()
    decryptor = MagicMock()
    svc = EventIntegrationsService(
        transaction=transaction,
        integrations=integrations,
        connections=connections,
        decryptor=decryptor,
        registry=registry,
    )
    return SimpleNamespace(
        svc=svc,
        transaction=transaction,
        integrations=integrations,
        connections=connections,
        decryptor=decryptor,
    )


def _create_data():
    return EventIntegrationCreateData(
        kind=IntegrationKind.IMPORT,
        implementation=_IMPL,
        connection_id=3,
        display_name="x",
        config_json="{}",
    )


class TestEventIntegrationsServiceCheck:
    def test_unknown_implementation_returns_not_found(self):
        env = _make_service(registry={})

        result = env.svc.check(
            IntegrationCheckRequest(
                sphere_id=1, implementation=_IMPL, connection_id=2, config_json="{}"
            )
        )

        assert result.outcome == CheckOutcome.NOT_FOUND
        assert _IMPL.value in result.hint
        # Short-circuits before touching the connection secret or decryptor.
        env.connections.read_secret.assert_not_called()
        env.decryptor.decrypt.assert_not_called()

    def test_invalid_config_returns_not_found(self):
        env = _make_service(registry={_IMPL: _ImportStubImpl()})

        result = env.svc.check(
            IntegrationCheckRequest(
                sphere_id=1,
                implementation=_IMPL,
                connection_id=2,
                # endpoint must be a string; a JSON number trips ValidationError.
                config_json='{"endpoint": 123}',
            )
        )

        assert result.outcome == CheckOutcome.NOT_FOUND
        assert "Invalid config" in result.hint
        # ValidationError funnels out before reading the secret.
        env.connections.read_secret.assert_not_called()
        env.decryptor.decrypt.assert_not_called()

    def test_missing_connection_returns_not_found(self):
        env = _make_service(registry={_IMPL: _ImportStubImpl()})
        env.connections.read_secret.side_effect = NotFoundError

        result = env.svc.check(
            IntegrationCheckRequest(
                sphere_id=1,
                implementation=_IMPL,
                connection_id=999,
                config_json='{"endpoint": "x"}',
            )
        )

        assert result.outcome == CheckOutcome.NOT_FOUND
        assert result.hint == "Connection not found."
        # A NotFoundError becomes a graceful result; nothing gets decrypted.
        env.decryptor.decrypt.assert_not_called()


class TestEventIntegrationsServiceRequireImplementation:
    def test_create_with_unknown_implementation_raises(self):
        env = _make_service(registry={})

        with pytest.raises(IntegrationImplementationNotFoundError):
            env.svc.create(sphere_id=1, event_id=2, data=_create_data())

        # Guard raises before any IO or transaction.
        env.connections.get.assert_not_called()
        env.transaction.atomic.assert_not_called()
        env.integrations.create.assert_not_called()

    def test_create_with_wrong_kind_raises(self):
        env = _make_service(registry={_IMPL: _TicketingStubImpl()})

        with pytest.raises(IntegrationImplementationNotFoundError):
            env.svc.create(sphere_id=1, event_id=2, data=_create_data())

        env.connections.get.assert_not_called()
        env.transaction.atomic.assert_not_called()
        env.integrations.create.assert_not_called()
