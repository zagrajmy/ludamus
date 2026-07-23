from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from ludamus.mills.chronology import (
    ConflictDetectionService,
    EventIntegrationsService,
    IntegrationImplementationNotFoundError,
    ProposalAcceptanceService,
    SessionConfirmationService,
    SessionContentEditService,
    TimetableOverviewService,
    TimetableService,
)
from ludamus.pacts import (
    AgendaItemDTO,
    EventDTO,
    NotFoundError,
    ScheduleChangeAction,
    SessionContentEditData,
    SessionDTO,
    SessionFieldValueData,
    SessionStatus,
    SpaceDTO,
    TimeSlotDTO,
)
from ludamus.pacts.chronology import (
    CapacityHoursDTO,
    CheckOutcome,
    CheckResult,
    ConflictType,
    ContentChangeNotLatestError,
    ContentChangeNotRevertibleError,
    EventIntegrationCreateData,
    IntegrationCheckRequest,
    IntegrationImplementationId,
    IntegrationKind,
    ProposalAcceptContextDTO,
    SessionPlacement,
    SourceQuestion,
    SpaceTimeConflictError,
)
from ludamus.pacts.crowd import UserDTO, UserType
from ludamus.pacts.submissions import ImportSettings


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
        uow.agenda_items.list_by_event.return_value = [item_a, item_b]

        svc = TimetableService(uow)
        grid = svc.build_grid(event_pk=1, tz=UTC)

        sessions = grid.days[0].columns[0].sessions
        expected_count = 2
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
        assert grid.selected_date is None
        assert grid.show_all_days is True
        uow.agenda_items.list_by_event.assert_called_once_with(1)


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

    def test_revert_unassign_raises_when_session_not_accepted(self, service, mock_uow):
        """Session must be in ACCEPTED status to revert an unassign."""
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

    def test_revert_unknown_action_raises(self, service, mock_uow):
        """Lines 240-241: unknown action type."""
        log = MagicMock()
        log.event_id = 1
        log.action = "UNKNOWN_ACTION"
        log.session_id = 1
        mock_uow.schedule_change_logs.read.return_value = log

        with pytest.raises(ValueError, match="Cannot revert action"):
            service.revert_change(log_pk=1, event_pk=1)


class TestContentEditRevert:
    @pytest.fixture
    def repos(self):
        repos = SimpleNamespace(
            transaction=MagicMock(),
            sessions=MagicMock(),
            session_fields=MagicMock(),
            content_change_logs=MagicMock(),
        )
        # By default the log under test (pk 1, session 5) is the latest change.
        repos.content_change_logs.latest_pk_for_session.return_value = 1
        return repos

    @pytest.fixture
    def service(self, repos):
        service = SessionContentEditService(
            repos.transaction,
            repos.sessions,
            repos.session_fields,
            repos.content_change_logs,
        )
        service.apply = MagicMock()
        return service

    @staticmethod
    def _log(*, changes, pk=1, event_id=1, session_id=5):
        log = MagicMock()
        log.pk = pk
        log.event_id = event_id
        log.session_id = session_id
        log.changes = changes
        return log

    def test_revert_builds_inverse_from_core_and_field_changes(self, service, repos):
        changes = [
            {"field": "title", "field_id": None, "old": "Old title", "new": "New"},
            {"field": "display_name", "field_id": None, "old": "Old host", "new": "H"},
            {"field": "description", "field_id": None, "old": "Old desc", "new": "D"},
            {"field": "contact_email", "field_id": None, "old": "a@b.co", "new": "x@y"},
            {"field": "duration", "field_id": None, "old": "01:00", "new": "02:00"},
            {"field": "category", "field_id": None, "old": 3, "new": 4},
            {"field": "participants_limit", "field_id": None, "old": 6, "new": 10},
            {"field": "min_age", "field_id": None, "old": 12, "new": 16},
            {"field": "", "field_id": 7, "old": "Pathfinder", "new": "DnD"},
            {"field": "", "field_id": 8, "old": None, "new": "Vegan"},
            {"field": "", "field_id": 9, "old": ["a", "b"], "new": ["a"]},
            {"field": "", "field_id": 10, "old": True, "new": False},
        ]
        repos.content_change_logs.read.return_value = self._log(changes=changes)

        service.revert(event_pk=1, log_pk=1, user_pk=9)

        repos.sessions.lock.assert_called_once_with(5)
        service.apply.assert_called_once_with(
            session_id=5,
            event_id=1,
            user_id=9,
            data=SessionContentEditData(
                update={
                    "title": "Old title",
                    "display_name": "Old host",
                    "description": "Old desc",
                    "contact_email": "a@b.co",
                    "duration": "01:00",
                    "category_id": 3,
                    "participants_limit": 6,
                    "min_age": 12,
                },
                field_values=[
                    SessionFieldValueData(session_id=5, field_id=7, value="Pathfinder"),
                    SessionFieldValueData(session_id=5, field_id=8, value=""),
                    SessionFieldValueData(session_id=5, field_id=9, value=["a", "b"]),
                    SessionFieldValueData(session_id=5, field_id=10, value=True),
                ],
            ),
        )

    def test_revert_drops_a_non_string_scalar_field_answer(self, service, repos):
        # ContentFieldValue admits int, but dynamic answers are str/list/bool;
        # a stray int answer is dropped rather than written back as one.
        changes = [
            {"field": "title", "field_id": None, "old": "Old title", "new": "New"},
            {"field": "", "field_id": 7, "old": 42, "new": "x"},
        ]
        repos.content_change_logs.read.return_value = self._log(changes=changes)

        service.revert(event_pk=1, log_pk=1, user_pk=9)

        service.apply.assert_called_once_with(
            session_id=5,
            event_id=1,
            user_id=9,
            data=SessionContentEditData(
                update={"title": "Old title"}, field_values=None
            ),
        )

    def test_revert_skips_cover_image_and_assignment_changes(self, service, repos):
        changes = [
            {"field": "cover_image", "field_id": None, "old": "", "new": "(updated)"},
            {"field": "facilitators", "field_id": None, "old": "Alice", "new": "Bob"},
            {"field": "tracks", "field_id": None, "old": "A", "new": "B"},
            {"field": "time_slots", "field_id": None, "old": "10 - 11", "new": ""},
            {"field": "title", "field_id": None, "old": "Old title", "new": "New"},
        ]
        repos.content_change_logs.read.return_value = self._log(changes=changes)

        service.revert(event_pk=1, log_pk=1, user_pk=9)

        service.apply.assert_called_once_with(
            session_id=5,
            event_id=1,
            user_id=9,
            data=SessionContentEditData(
                update={"title": "Old title"}, field_values=None
            ),
        )

    def test_revert_raises_when_nothing_is_revertible(self, service, repos):
        changes = [
            {"field": "cover_image", "field_id": None, "old": "old.png", "new": ""}
        ]
        repos.content_change_logs.read.return_value = self._log(changes=changes)

        with pytest.raises(ContentChangeNotRevertibleError):
            service.revert(event_pk=1, log_pk=1, user_pk=9)

        service.apply.assert_not_called()

    def test_revert_rejects_non_latest_change(self, service, repos):
        changes = [
            {"field": "title", "field_id": None, "old": "Old title", "new": "New"}
        ]
        repos.content_change_logs.read.return_value = self._log(changes=changes)
        # A newer change (pk 2) exists for the same session.
        repos.content_change_logs.latest_pk_for_session.return_value = 2

        with pytest.raises(ContentChangeNotLatestError):
            service.revert(event_pk=1, log_pk=1, user_pk=9)

        service.apply.assert_not_called()

    def test_revert_raises_not_found_for_log_from_another_event(self, service, repos):
        changes = [
            {"field": "title", "field_id": None, "old": "Old title", "new": "New"}
        ]
        repos.content_change_logs.read.return_value = self._log(
            changes=changes, event_id=2
        )

        with pytest.raises(NotFoundError):
            service.revert(event_pk=1, log_pk=1, user_pk=9)

        repos.sessions.lock.assert_not_called()
        service.apply.assert_not_called()

    def test_revert_of_revert_restores_the_edit(self, service, repos):
        # First revert: undo "Old title" -> "New title".
        edit_log = self._log(
            changes=[{"field": "title", "field_id": None, "old": "Old", "new": "New"}]
        )
        repos.content_change_logs.read.return_value = edit_log

        service.revert(event_pk=1, log_pk=1, user_pk=9)

        service.apply.assert_called_once_with(
            session_id=5,
            event_id=1,
            user_id=9,
            data=SessionContentEditData(update={"title": "Old"}, field_values=None),
        )

        # The revert's own audit row (mirrored old/new) is now the latest
        # change; reverting it restores the original edit.
        revert_log = self._log(
            changes=[{"field": "title", "field_id": None, "old": "New", "new": "Old"}],
            pk=2,
        )
        repos.content_change_logs.read.return_value = revert_log
        repos.content_change_logs.latest_pk_for_session.return_value = 2
        service.apply.reset_mock()

        service.revert(event_pk=1, log_pk=2, user_pk=9)

        service.apply.assert_called_once_with(
            session_id=5,
            event_id=1,
            user_id=9,
            data=SessionContentEditData(update={"title": "New"}, field_values=None),
        )

    def test_revertible_log_pks_marks_latest_invertible_rows(self, service, repos):
        title_change = {"field": "title", "field_id": None, "old": "Old", "new": "New"}
        cover_change = {
            "field": "cover_image",
            "field_id": None,
            "old": "",
            "new": "(updated)",
        }
        repos.content_change_logs.latest_pks_by_session.return_value = {5: 3, 6: 4}
        repos.content_change_logs.list_by_event.return_value = [
            self._log(changes=[title_change], pk=3, session_id=5),
            self._log(changes=[title_change], pk=2, session_id=5),
            self._log(changes=[cover_change], pk=4, session_id=6),
        ]

        assert service.revertible_log_pks(1) == {3}


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
        session.title = "Subject"
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

        assert result == CapacityHoursDTO(
            room_count=2,
            slot_hours=4.0,
            capacity_hours=8.0,
            scheduled_hours=0.0,
            hours_to_fill=8.0,
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


# --- EventIntegrationsService ---


class _StrictConfig(BaseModel):
    endpoint: str


class _ImportStubImpl:
    kind = IntegrationKind.IMPORT
    config_model = _StrictConfig

    def check(self, secret, config):
        return CheckResult(outcome=CheckOutcome.OK, hint="")


class _HeaderStubImpl:
    kind = IntegrationKind.IMPORT
    config_model = _StrictConfig

    def __init__(self, headers):
        self._headers = headers

    def check(self, secret, config):
        return CheckResult(outcome=CheckOutcome.OK, hint="")

    def fetch_questions(self, **_kwargs):
        return [SourceQuestion(title="Tytuł")]

    def fetch_headers(self, **_kwargs):
        return self._headers


class _TicketingStubImpl:
    kind = IntegrationKind.TICKETING
    config_model = BaseModel

    def check(self, secret, config):
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


class TestEventIntegrationsServiceSnapshotAndFetch:
    def test_fetch_questions_returns_empty_when_implementation_missing(self):
        env = _make_service(registry={})
        env.integrations.get.return_value = MagicMock(implementation=_IMPL)

        result = env.svc.fetch_questions(sphere_id=1, event_id=2, pk=3)

        assert result == []
        # No registered impl: short-circuits before touching the secret.
        env.connections.read_secret.assert_not_called()
        env.decryptor.decrypt.assert_not_called()

    def test_fetch_responses_returns_empty_when_implementation_missing(self):
        env = _make_service(registry={})
        env.integrations.get.return_value = MagicMock(implementation=_IMPL)

        result = env.svc.fetch_responses(sphere_id=1, event_id=2, pk=3)

        assert result == []
        env.connections.read_secret.assert_not_called()
        env.decryptor.decrypt.assert_not_called()

    def test_fetch_headers_returns_empty_when_implementation_missing(self):
        env = _make_service(registry={})
        env.integrations.get.return_value = MagicMock(implementation=_IMPL)

        result = env.svc.fetch_headers(sphere_id=1, event_id=2, pk=3)

        assert result == []
        env.connections.read_secret.assert_not_called()
        env.decryptor.decrypt.assert_not_called()

    def test_populate_snapshot_caches_the_sheet_header_row(self):
        # The header row is what the run tab offers as unique-key columns, so it
        # must include the metadata columns the form schema never carries.
        headers = ["Sygnatura czasowa", "Adres e-mail", "Tytuł"]
        event_id, pk = 2, 3
        impl = _HeaderStubImpl(headers=headers)
        env = _make_service(registry={_IMPL: impl})
        env.integrations.get.return_value = MagicMock(
            implementation=_IMPL, config_json='{"endpoint": "x"}', settings_json="{}"
        )

        env.svc.populate_questions_snapshot(sphere_id=1, event_id=event_id, pk=pk)

        saved = env.integrations.update_settings.call_args.kwargs
        assert saved["event_id"] == event_id
        assert saved["pk"] == pk
        assert (
            ImportSettings.model_validate_json(saved["settings_json"]).sheet_headers
            == headers
        )

    def test_populate_snapshot_keeps_cached_headers_when_the_fetch_fails(self):
        # A transient Sheets failure yields []; wiping the cache would empty the
        # unique-key select the operator already configured against.
        env = _make_service(registry={_IMPL: _HeaderStubImpl(headers=[])})
        env.integrations.get.return_value = MagicMock(
            implementation=_IMPL,
            config_json='{"endpoint": "x"}',
            settings_json='{"sheet_headers": ["Sygnatura czasowa"]}',
        )

        env.svc.populate_questions_snapshot(sphere_id=1, event_id=2, pk=3)

        env.integrations.update_settings.assert_not_called()
        env.integrations.update_questions_snapshot.assert_called_once()

    def test_get_cached_questions_returns_empty_on_invalid_snapshot_json(self):
        env = _make_service(registry={})
        env.integrations.get.return_value = MagicMock(
            questions_snapshot_json="not valid json"
        )

        assert env.svc.get_cached_questions(2, 3) == []


_NOW = datetime(2024, 6, 1, 12, 0, tzinfo=UTC)
_SESSION_PK = 5


def _session_dto(**overrides):
    defaults = {
        "category_id": None,
        "contact_email": "",
        "creation_time": _NOW,
        "description": "",
        "min_age": 0,
        "modification_time": _NOW,
        "participants_limit": 0,
        "pk": _SESSION_PK,
        "presenter_id": None,
        "display_name": "Alice",
        "slug": "s",
        "status": SessionStatus.PENDING,
        "title": "My Session",
    }
    return SessionDTO(**(defaults | overrides))


def _event_dto(**overrides):
    defaults = {
        "description": "",
        "end_time": _NOW,
        "name": "Con",
        "pk": 9,
        "proposal_end_time": None,
        "proposal_start_time": None,
        "publication_time": None,
        "slug": "con",
        "sphere_id": 3,
        "start_time": _NOW,
    }
    return EventDTO(**(defaults | overrides))


def _user_dto(**overrides):
    defaults = {
        "avatar_url": "",
        "date_joined": _NOW,
        "discord_username": "",
        "email": "",
        "full_name": "",
        "is_active": True,
        "is_authenticated": True,
        "is_staff": False,
        "is_superuser": False,
        "name": "",
        "pk": 1,
        "slug": "manager",
        "use_gravatar": False,
        "user_type": UserType.ACTIVE,
        "username": "auth0|sub",
    }
    return UserDTO(**(defaults | overrides))


class TestProposalAcceptanceService:
    @pytest.fixture
    def sessions(self):
        return MagicMock()

    @pytest.fixture
    def agenda_items(self):
        return MagicMock()

    @pytest.fixture
    def active_users(self):
        return MagicMock()

    @pytest.fixture
    def spheres(self):
        return MagicMock()

    @pytest.fixture
    def transaction(self):
        transaction = MagicMock()
        transaction.atomic.return_value.__enter__.return_value = None
        return transaction

    @pytest.fixture
    def service(self, transaction, sessions, agenda_items, active_users, spheres):
        return ProposalAcceptanceService(
            transaction=transaction,
            sessions=sessions,
            agenda_items=agenda_items,
            active_users=active_users,
            spheres=spheres,
        )

    @staticmethod
    def _arrange_reads(sessions, active_users):
        sessions.read.return_value = _session_dto()
        sessions.read_event.return_value = _event_dto()
        sessions.read_presenter.return_value = None
        sessions.read_space_options.return_value = []
        sessions.read_time_slots.return_value = []
        sessions.read_preferred_time_slot_ids.return_value = []
        sessions.read_field_values.return_value = []
        active_users.read.return_value = _user_dto()

    def test_get_accept_context_returns_none_when_session_missing(
        self, service, sessions
    ):
        sessions.read.side_effect = NotFoundError

        assert (
            service.get_accept_context(session_id=5, user_slug="u", sphere_id=3) is None
        )

    def test_get_accept_context_assembles_dto(
        self, service, sessions, active_users, spheres
    ):
        self._arrange_reads(sessions, active_users)
        spheres.is_manager.return_value = True

        context = service.get_accept_context(
            session_id=5, user_slug="manager", sphere_id=3
        )

        assert isinstance(context, ProposalAcceptContextDTO)
        assert context.session.pk == _SESSION_PK
        assert context.event.slug == "con"
        assert context.presenter is None
        assert context.space_options == []
        assert context.can_accept is True

    def test_can_accept_true_for_superuser_without_manager_check(
        self, service, sessions, active_users, spheres
    ):
        self._arrange_reads(sessions, active_users)
        active_users.read.return_value = _user_dto(is_superuser=True)

        context = service.get_accept_context(
            session_id=5, user_slug="root", sphere_id=3
        )

        assert context is not None
        assert context.can_accept is True
        spheres.is_manager.assert_not_called()

    def test_can_accept_true_for_staff(self, service, sessions, active_users, spheres):
        self._arrange_reads(sessions, active_users)
        active_users.read.return_value = _user_dto(is_staff=True)

        context = service.get_accept_context(
            session_id=5, user_slug="staff", sphere_id=3
        )

        assert context is not None
        assert context.can_accept is True
        spheres.is_manager.assert_not_called()

    def test_can_accept_falls_back_to_sphere_manager(
        self, service, sessions, active_users, spheres
    ):
        self._arrange_reads(sessions, active_users)
        spheres.is_manager.return_value = False

        context = service.get_accept_context(
            session_id=5, user_slug="member", sphere_id=3
        )

        assert context is not None
        assert context.can_accept is False
        spheres.is_manager.assert_called_once_with(3, "member")

    def test_accept_session_updates_status_and_creates_agenda_item(
        self, service, sessions, agenda_items, transaction
    ):
        sessions.read.return_value = _session_dto(pk=5, display_name="Alice")
        sessions.read_time_slot.return_value = SimpleNamespace(
            start_time=_NOW, end_time=_NOW
        )
        agenda_items.list_overlapping_in_space.return_value = []

        service.accept_session(session_id=5, space_id=7, time_slot_id=2)

        sessions.read_time_slot.assert_called_once_with(5, 2)
        agenda_items.list_overlapping_in_space.assert_called_once_with(
            7, _NOW, _NOW, exclude_session_pk=5
        )
        sessions.update.assert_called_once_with(
            5, {"status": SessionStatus.ACCEPTED, "display_name": "Alice"}
        )
        agenda_items.create.assert_called_once_with(
            {
                "space_id": 7,
                "session_id": 5,
                "session_confirmed": True,
                "start_time": _NOW,
                "end_time": _NOW,
            }
        )
        transaction.atomic.assert_called_once_with()

    def test_accept_session_raises_on_space_time_conflict(
        self, service, sessions, agenda_items
    ):
        sessions.read.return_value = _session_dto(pk=5, display_name="Alice")
        sessions.read_time_slot.return_value = SimpleNamespace(
            start_time=_NOW, end_time=_NOW
        )
        agenda_items.list_overlapping_in_space.return_value = [
            _make_item(pk=9, space_id=7)
        ]

        with pytest.raises(SpaceTimeConflictError):
            service.accept_session(session_id=5, space_id=7, time_slot_id=2)

        sessions.update.assert_not_called()
        agenda_items.create.assert_not_called()
