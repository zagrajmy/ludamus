from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ludamus.mills.chronology import (
    ProposalAcceptanceService,
    ProposalStatusService,
    SessionConfirmationService,
    SessionContentEditService,
    SessionDeletionService,
)
from ludamus.pacts import (
    AgendaItemDTO,
    ContentChangeLogDTO,
    FacilitatorDTO,
    NotFoundError,
    ScheduleChangeAction,
    SessionContentEditData,
    SessionFieldValueData,
    SessionFieldValueDTO,
    SessionStatus,
    TimeSlotDTO,
)
from ludamus.pacts.chronology import (
    ContentChangeNotLatestError,
    ContentChangeNotRevertibleError,
    ProposalAcceptDeniedError,
    ProposalScheduledError,
    SpaceTimeConflictError,
)
from ludamus.pacts.multiverse import SphereRole
from tests.unit.factories import (
    FakeTransaction,
    event_dto,
    session_dto,
    track_dto,
    user_dto,
)


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


class TestContentEditRevert:
    @pytest.fixture
    def repos(self):
        repos = SimpleNamespace(
            transaction=FakeTransaction(),
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
            transaction=repos.transaction,
            sessions=repos.sessions,
            session_fields=repos.session_fields,
            content_change_logs=repos.content_change_logs,
            agenda_items=MagicMock(),
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
            {
                "field": "facilitator_name",
                "field_id": None,
                "old": "Old host",
                "new": "H",
            },
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
                    "facilitator_name": "Old host",
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

    def test_session_history_rejects_cross_event_session(self, service, repos):
        repos.sessions.read_event.return_value = SimpleNamespace(pk=2)

        with pytest.raises(NotFoundError):
            service.session_history(event_id=1, session_id=5)

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


class TestContentEditStoresAnswers:
    @pytest.fixture
    def repos(self):
        repos = SimpleNamespace(
            transaction=FakeTransaction(),
            sessions=MagicMock(),
            session_fields=MagicMock(),
            content_change_logs=MagicMock(),
            agenda_items=MagicMock(),
        )
        repos.sessions.read_field_values.return_value = []
        repos.session_fields.list_by_event.return_value = []
        return repos

    @pytest.fixture
    def service(self, repos):
        return SessionContentEditService(
            transaction=repos.transaction,
            sessions=repos.sessions,
            session_fields=repos.session_fields,
            content_change_logs=repos.content_change_logs,
            agenda_items=repos.agenda_items,
        )

    def test_blank_answer_clears_a_field_that_has_one(self, service, repos):
        repos.sessions.read_field_values.return_value = [
            MagicMock(field_id=7, value="Pathfinder")
        ]

        service.apply(
            session_id=5,
            event_id=1,
            user_id=9,
            data=SessionContentEditData(
                update={},
                field_values=[
                    SessionFieldValueData(session_id=5, field_id=7, value=""),
                    SessionFieldValueData(session_id=5, field_id=8, value=""),
                ],
            ),
        )

        repos.sessions.save_field_values.assert_called_once_with(
            5, [SessionFieldValueData(session_id=5, field_id=7, value="")]
        )

    def test_an_unchecked_checkbox_is_stored_as_an_answer(self, service, repos):
        service.apply(
            session_id=5,
            event_id=1,
            user_id=9,
            data=SessionContentEditData(
                update={},
                field_values=[
                    SessionFieldValueData(session_id=5, field_id=7, value=False)
                ],
            ),
        )

        repos.sessions.save_field_values.assert_called_once_with(
            5, [SessionFieldValueData(session_id=5, field_id=7, value=False)]
        )


class TestContentEditResizesAgendaItem:
    @pytest.fixture
    def repos(self):
        repos = SimpleNamespace(
            transaction=FakeTransaction(),
            sessions=MagicMock(),
            session_fields=MagicMock(),
            content_change_logs=MagicMock(),
            agenda_items=MagicMock(),
        )
        repos.sessions.read.return_value = _session_dto(duration="PT1H")
        repos.sessions.read_field_values.return_value = []
        repos.agenda_items.read_by_session.return_value = _make_item()
        return repos

    @pytest.fixture
    def service(self, repos):
        return SessionContentEditService(
            transaction=repos.transaction,
            sessions=repos.sessions,
            session_fields=repos.session_fields,
            content_change_logs=repos.content_change_logs,
            agenda_items=repos.agenda_items,
        )

    @staticmethod
    def _apply(service, duration):
        service.apply(
            session_id=1,
            event_id=1,
            user_id=9,
            data=SessionContentEditData(update={"duration": duration}),
        )

    def test_a_longer_duration_moves_the_end_time(self, service, repos):
        self._apply(service, "PT2H30M")

        repos.agenda_items.update.assert_called_once_with(
            1, {"end_time": datetime(2026, 1, 1, 12, 30, tzinfo=UTC)}
        )

    # "PT2Hjunk" and "P1DT2H" are the ones a lenient parser gets wrong: the
    # first would resize a real block to two hours, the second to zero.
    @pytest.mark.parametrize("duration", ("PT2Hjunk", "P1DT2H"))
    def test_a_duration_that_is_not_a_length_writes_nothing(
        self, service, repos, duration
    ):
        self._apply(service, duration)

        repos.agenda_items.update.assert_not_called()


class TestSessionConfirmation:
    @pytest.fixture
    def agenda_items(self):
        return MagicMock()

    @pytest.fixture
    def sessions(self):
        return MagicMock()

    @pytest.fixture
    def transaction(self):
        transaction = MagicMock()
        transaction.atomic.return_value.__enter__.return_value = None
        return transaction

    @pytest.fixture
    def service(self, transaction, agenda_items, sessions):
        return SessionConfirmationService(transaction, agenda_items, sessions)

    @staticmethod
    def _event(pk):
        event = MagicMock()
        event.pk = pk
        return event

    def test_rejects_session_from_another_event(self, service, agenda_items, sessions):
        sessions.read_event.return_value = self._event(2)

        with pytest.raises(NotFoundError):
            service.set_session_confirmed(event_pk=1, session_pk=3, confirmed=True)

        sessions.update.assert_not_called()
        agenda_items.update.assert_not_called()

    def test_rejects_a_session_not_on_the_timetable(
        self, service, agenda_items, sessions
    ):
        agenda_items.read_by_session.return_value = None
        sessions.read_event.return_value = self._event(1)

        with pytest.raises(NotFoundError):
            service.set_session_confirmed(event_pk=1, session_pk=3, confirmed=True)

        sessions.update.assert_not_called()
        agenda_items.update.assert_not_called()


_NOW = datetime(2024, 6, 1, 12, 0, tzinfo=UTC)
_SESSION_PK = 5


def _session_dto(**overrides):
    return session_dto(
        **{
            "creation_time": _NOW,
            "facilitator_name": "Alice",
            "modification_time": _NOW,
            "pk": _SESSION_PK,
            "status": SessionStatus.PENDING,
            "title": "My Session",
            **overrides,
        }
    )


def _event_dto(**overrides):
    return event_dto(
        **{
            "end_time": _NOW,
            "name": "Con",
            "pk": 9,
            "slug": "con",
            "sphere_id": 3,
            "start_time": _NOW,
            **overrides,
        }
    )


def _user_dto(**overrides):
    return user_dto(**{"date_joined": _NOW, **overrides})


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
        spheres.manager_role.assert_not_called()

    def test_can_accept_false_for_non_manager_staff(
        self, service, sessions, active_users, spheres
    ):
        self._arrange_reads(sessions, active_users)
        active_users.read.return_value = _user_dto(is_staff=True)
        spheres.manager_role.return_value = None

        context = service.get_accept_context(
            session_id=5, user_slug="staff", sphere_id=3
        )

        assert context is not None
        assert context.can_accept is False
        spheres.manager_role.assert_called_once_with(3, "staff")

    def test_can_accept_falls_back_to_sphere_manager(
        self, service, sessions, active_users, spheres
    ):
        self._arrange_reads(sessions, active_users)
        spheres.manager_role.return_value = None

        context = service.get_accept_context(
            session_id=5, user_slug="member", sphere_id=3
        )

        assert context is not None
        assert context.can_accept is False
        spheres.manager_role.assert_called_once_with(3, "member")

    def test_accept_session_raises_on_space_time_conflict(
        self, service, sessions, agenda_items, active_users, spheres
    ):
        sessions.read.return_value = _session_dto(pk=5, facilitator_name="Alice")
        sessions.read_time_slot.return_value = SimpleNamespace(
            start_time=_NOW, end_time=_NOW
        )
        agenda_items.list_overlapping_in_space.return_value = [
            _make_item(pk=9, space_id=7)
        ]
        active_users.read.return_value = _user_dto()
        spheres.manager_role.return_value = SphereRole.MANAGER

        with pytest.raises(SpaceTimeConflictError):
            service.accept_session(
                session_id=5,
                space_id=7,
                time_slot_id=2,
                user_slug="manager",
                sphere_id=3,
            )

        sessions.update.assert_not_called()
        agenda_items.create.assert_not_called()

    def test_accept_session_allowed_for_superuser(
        self, service, sessions, agenda_items, active_users, spheres
    ):
        sessions.read.return_value = _session_dto(pk=5, facilitator_name="Alice")
        sessions.read_time_slot.return_value = SimpleNamespace(
            start_time=_NOW, end_time=_NOW
        )
        sessions.read_event.return_value = _event_dto(auto_confirm_sessions=True)
        agenda_items.list_overlapping_in_space.return_value = []
        active_users.read.return_value = _user_dto(is_superuser=True)

        service.accept_session(
            session_id=5, space_id=7, time_slot_id=2, user_slug="root", sphere_id=3
        )

        sessions.update.assert_called_once_with(
            5,
            {
                "status": SessionStatus.ACCEPTED,
                "facilitator_name": "Alice",
                "schedule_confirmed": True,
            },
        )
        spheres.manager_role.assert_not_called()

    def test_accept_session_denied_for_comms_member(
        self, service, sessions, agenda_items, active_users, spheres
    ):
        active_users.read.return_value = _user_dto()
        spheres.manager_role.return_value = SphereRole.COMMS

        with pytest.raises(ProposalAcceptDeniedError):
            service.accept_session(
                session_id=5, space_id=7, time_slot_id=2, user_slug="press", sphere_id=3
            )

        sessions.update.assert_not_called()
        agenda_items.create.assert_not_called()

    def test_accept_session_denied_for_non_manager(
        self, service, sessions, agenda_items, active_users, spheres
    ):
        active_users.read.return_value = _user_dto()
        spheres.manager_role.return_value = None

        with pytest.raises(ProposalAcceptDeniedError):
            service.accept_session(
                session_id=5,
                space_id=7,
                time_slot_id=2,
                user_slug="member",
                sphere_id=3,
            )

        sessions.update.assert_not_called()
        agenda_items.create.assert_not_called()

    def test_missing_session_has_no_accept_context(self, service, sessions):
        sessions.read.side_effect = NotFoundError

        assert (
            service.get_accept_context(session_id=5, user_slug="root", sphere_id=3)
            is None
        )


class _FakeSessions:
    def __init__(self, *sessions, event=None):
        self.rows = {session.pk: session for session in sessions}
        self.event = event or _event_dto()
        self.updates: dict[int, dict] = {}
        self.field_values: list = []
        self.related: dict[str, dict] = {
            "facilitators": {},
            "tracks": {},
            "time_slots": {},
        }
        self.related_ids: dict[str, list[int]] = {
            "facilitators": [],
            "tracks": [],
            "time_slots": [],
        }
        self.calls: dict[str, list] = {
            "locked": [],
            "deleted": [],
            "restored": [],
            "deleted_field_ids": [],
        }

    def read(self, pk):
        try:
            return self.rows[pk]
        except KeyError:
            raise NotFoundError from None

    def read_event(self, session_id):
        self.read(session_id)
        return self.event

    def lock(self, pk):
        self.read(pk)
        self.calls["locked"].append(pk)

    def update(self, pk, data):
        self.updates.setdefault(pk, {}).update(data)

    def soft_delete(self, pk):
        self.calls["deleted"].append(pk)

    def restore(self, pk, event_pk):
        self.calls["restored"].append((pk, event_pk))

    def read_field_values(self, session_id):
        return list(self.field_values)

    def delete_field_values_for_fields(self, session_id, field_ids):
        self.calls["deleted_field_ids"].append((session_id, field_ids))

    def read_facilitators(self, session_id):
        return self._related("facilitators")

    def set_facilitators(self, session_id, facilitator_ids):
        self.related_ids["facilitators"] = facilitator_ids

    def read_tracks(self, session_id):
        return self._related("tracks")

    def set_session_tracks(self, session_pk, track_pks):
        self.related_ids["tracks"] = track_pks

    def read_preferred_time_slots(self, session_id):
        return self._related("time_slots")

    def set_time_slots(self, session_id, time_slot_ids):
        self.related_ids["time_slots"] = time_slot_ids

    def _related(self, kind):
        return [self.related[kind][pk] for pk in self.related_ids[kind]]


class _FakeAgendaItems:
    def __init__(self, *items):
        self.rows = {item.pk: item for item in items}
        self.updates: dict[int, dict] = {}

    def read_by_session(self, session_pk):
        return next(
            (item for item in self.rows.values() if item.session_id == session_pk), None
        )

    def update(self, pk, data):
        self.updates.setdefault(pk, {}).update(data)

    def delete(self, pk):
        del self.rows[pk]


class _FakeScheduleChangeLogs:
    def __init__(self):
        self.rows: list = []

    def create(self, data):
        self.rows.append(data)
        return len(self.rows)


class _FakeContentChangeLogs:
    def __init__(self, *logs):
        self.rows = list(logs)
        self.created: list = []

    def create(self, data):
        self.created.append(data)

    def read(self, pk):
        return next(log for log in self.rows if log.pk == pk)

    def list_by_event(self, event_pk):
        return [log for log in self.rows if log.event_id == event_pk]

    def latest_pks_by_session(self, event_pk):
        latest: dict[int, int] = {}
        for log in self.list_by_event(event_pk):
            latest[log.session_id] = max(latest.get(log.session_id, 0), log.pk)
        return latest

    def latest_pk_for_session(self, event_pk, session_id):
        return self.latest_pks_by_session(event_pk).get(session_id)


_EVENT_PK = 9


class TestSessionConfirmationOfOwnEvent:
    def test_confirms_an_item_whose_session_belongs_to_the_event(self):
        agenda_items = _FakeAgendaItems(_make_item(pk=7, session_id=_SESSION_PK))
        sessions = _FakeSessions(_session_dto())
        service = SessionConfirmationService(FakeTransaction(), agenda_items, sessions)

        service.set_session_confirmed(
            event_pk=_EVENT_PK, session_pk=_SESSION_PK, confirmed=True
        )

        assert agenda_items.updates == {7: {"session_confirmed": True}}
        assert sessions.updates == {_SESSION_PK: {"schedule_confirmed": True}}


class TestSessionDeletion:
    @staticmethod
    def _service(sessions, agenda_items, logs):
        return SessionDeletionService(FakeTransaction(), sessions, agenda_items, logs)

    def test_soft_delete_frees_the_slot_and_logs_the_unassignment(self):
        item = _make_item(pk=7, session_id=_SESSION_PK, space_id=4)
        sessions = _FakeSessions(_session_dto(status=SessionStatus.ACCEPTED))
        agenda_items = _FakeAgendaItems(item)
        logs = _FakeScheduleChangeLogs()

        self._service(sessions, agenda_items, logs).soft_delete(
            _EVENT_PK, _SESSION_PK, user_pk=3
        )

        assert agenda_items.rows == {}
        assert sessions.updates == {
            _SESSION_PK: {"status": SessionStatus.PENDING, "schedule_confirmed": False}
        }
        assert sessions.calls["deleted"] == [_SESSION_PK]
        assert logs.rows == [
            {
                "event_id": _EVENT_PK,
                "session_id": _SESSION_PK,
                "user_id": 3,
                "action": ScheduleChangeAction.UNASSIGN,
                "old_space_id": 4,
                "old_start_time": item.start_time,
                "old_end_time": item.end_time,
            }
        ]

    def test_soft_delete_of_an_unscheduled_session_writes_no_log(self):
        sessions = _FakeSessions(_session_dto())
        logs = _FakeScheduleChangeLogs()

        self._service(sessions, _FakeAgendaItems(), logs).soft_delete(
            _EVENT_PK, _SESSION_PK
        )

        assert sessions.calls["deleted"] == [_SESSION_PK]
        assert not sessions.updates
        assert not logs.rows

    def test_soft_delete_rejects_a_session_from_another_event(self):
        sessions = _FakeSessions(_session_dto())
        agenda_items = _FakeAgendaItems(_make_item(pk=7, session_id=_SESSION_PK))

        with pytest.raises(NotFoundError):
            self._service(
                sessions, agenda_items, _FakeScheduleChangeLogs()
            ).soft_delete(_EVENT_PK + 1, _SESSION_PK)

        assert not sessions.calls["deleted"]
        assert agenda_items.read_by_session(_SESSION_PK) is not None

    def test_soft_delete_of_a_missing_session_is_not_found(self):
        sessions = _FakeSessions()

        with pytest.raises(NotFoundError):
            self._service(
                sessions, _FakeAgendaItems(), _FakeScheduleChangeLogs()
            ).soft_delete(_EVENT_PK, _SESSION_PK)

    def test_restore_scopes_the_session_to_the_event(self):
        sessions = _FakeSessions()

        self._service(sessions, _FakeAgendaItems(), _FakeScheduleChangeLogs()).restore(
            _EVENT_PK, _SESSION_PK
        )

        assert sessions.calls["restored"] == [(_SESSION_PK, _EVENT_PK)]


class TestProposalStatus:
    @staticmethod
    def _service(sessions, agenda_items):
        return ProposalStatusService(
            transaction=FakeTransaction(), sessions=sessions, agenda_items=agenda_items
        )

    @pytest.mark.parametrize(
        ("method", "status"),
        (
            ("mark_pending", SessionStatus.PENDING),
            ("mark_accepted", SessionStatus.ACCEPTED),
            ("mark_on_hold", SessionStatus.ON_HOLD),
            ("mark_rejected", SessionStatus.REJECTED),
        ),
    )
    def test_marks_an_unscheduled_session(self, method, status):
        sessions = _FakeSessions(_session_dto())

        getattr(self._service(sessions, _FakeAgendaItems()), method)(
            event_pk=_EVENT_PK, session_pk=_SESSION_PK
        )

        assert sessions.updates == {_SESSION_PK: {"status": status}}
        assert sessions.calls["locked"] == [_SESSION_PK]

    def test_a_scheduled_session_cannot_leave_accepted(self):
        sessions = _FakeSessions(_session_dto(status=SessionStatus.ACCEPTED))
        agenda_items = _FakeAgendaItems(_make_item(session_id=_SESSION_PK))

        with pytest.raises(ProposalScheduledError):
            self._service(sessions, agenda_items).mark_rejected(
                event_pk=_EVENT_PK, session_pk=_SESSION_PK
            )

        assert not sessions.updates

    def test_a_scheduled_session_can_be_re_accepted(self):
        sessions = _FakeSessions(_session_dto(status=SessionStatus.ACCEPTED))
        agenda_items = _FakeAgendaItems(_make_item(session_id=_SESSION_PK))

        self._service(sessions, agenda_items).mark_accepted(
            event_pk=_EVENT_PK, session_pk=_SESSION_PK
        )

        assert sessions.updates == {_SESSION_PK: {"status": SessionStatus.ACCEPTED}}

    def test_rejects_a_session_from_another_event(self):
        sessions = _FakeSessions(_session_dto())

        with pytest.raises(NotFoundError):
            self._service(sessions, _FakeAgendaItems()).mark_on_hold(
                event_pk=_EVENT_PK + 1, session_pk=_SESSION_PK
            )

        assert not sessions.updates


def _content_log(*, changes, pk=1, event_id=_EVENT_PK, session_id=_SESSION_PK):
    return ContentChangeLogDTO(
        pk=pk,
        event_id=event_id,
        session_id=session_id,
        session_title="My Session",
        user_id=None,
        user_name="",
        changes=changes,
        creation_time=_NOW,
    )


def _facilitator_dto(pk, display_name):
    return FacilitatorDTO(
        accreditation_type="",
        display_name=display_name,
        event_id=_EVENT_PK,
        pk=pk,
        slug=f"f-{pk}",
        user_id=None,
    )


def _track_dto(pk, name):
    return track_dto(
        creation_time=_NOW,
        event_id=_EVENT_PK,
        modification_time=_NOW,
        name=name,
        pk=pk,
        slug=f"t-{pk}",
    )


class TestContentEditWithFakes:
    @staticmethod
    def _service(sessions, logs, *, agenda_items=None, session_fields=None):
        return SessionContentEditService(
            transaction=FakeTransaction(),
            sessions=sessions,
            session_fields=session_fields or MagicMock(),
            content_change_logs=logs,
            agenda_items=agenda_items or _FakeAgendaItems(),
        )

    @staticmethod
    def _field_value(field_id, value):
        return SessionFieldValueDTO(
            field_id=field_id, field_name="", field_question="", value=value
        )

    def test_dropping_answers_of_removed_fields_logs_them_for_revert(self):
        sessions = _FakeSessions(_session_dto())
        sessions.field_values = [self._field_value(7, "Pathfinder")]
        logs = _FakeContentChangeLogs()

        self._service(sessions, logs).apply(
            session_id=_SESSION_PK,
            event_id=_EVENT_PK,
            user_id=3,
            data=SessionContentEditData(update={}, remove_field_ids=[7, 99]),
        )

        assert sessions.calls["deleted_field_ids"] == [(_SESSION_PK, [7])]
        assert logs.created == [
            {
                "event_id": _EVENT_PK,
                "session_id": _SESSION_PK,
                "user_id": 3,
                "changes": [
                    {"field": "", "field_id": 7, "old": "Pathfinder", "new": None}
                ],
            }
        ]

    def test_removing_only_unanswered_fields_changes_nothing(self):
        sessions = _FakeSessions(_session_dto())
        logs = _FakeContentChangeLogs()

        self._service(sessions, logs).apply(
            session_id=_SESSION_PK,
            event_id=_EVENT_PK,
            user_id=3,
            data=SessionContentEditData(update={}, remove_field_ids=[99]),
        )

        assert not sessions.calls["deleted_field_ids"]
        assert not logs.created

    def test_replacing_assignments_logs_names_not_ids(self):
        sessions = _FakeSessions(_session_dto())
        sessions.related["facilitators"] = {
            1: _facilitator_dto(1, "Bob"),
            2: _facilitator_dto(2, "Alice"),
        }
        sessions.related_ids["facilitators"] = [1]
        sessions.related["tracks"] = {4: _track_dto(4, "RPG")}
        sessions.related_ids["tracks"] = [4]
        sessions.related["time_slots"] = {
            8: TimeSlotDTO(pk=8, start_time=_NOW, end_time=_NOW + timedelta(hours=2))
        }
        logs = _FakeContentChangeLogs()

        self._service(sessions, logs).apply(
            session_id=_SESSION_PK,
            event_id=_EVENT_PK,
            user_id=3,
            data=SessionContentEditData(
                update={}, facilitator_ids=[2, 1], track_ids=[4], time_slot_ids=[8]
            ),
        )

        assert sessions.related_ids == {
            "facilitators": [2, 1],
            "tracks": [4],
            "time_slots": [8],
        }
        assert logs.created[0]["changes"] == [
            {
                "field": "facilitators",
                "field_id": None,
                "old": "Bob",
                "new": "Alice, Bob",
            },
            {
                "field": "time_slots",
                "field_id": None,
                "old": "",
                "new": "2024-06-01T12:00:00+00:00 - 2024-06-01T14:00:00+00:00",
            },
        ]

    def test_a_duration_change_on_an_unscheduled_session_touches_no_block(self):
        sessions = _FakeSessions(_session_dto(duration="PT1H"))
        agenda_items = _FakeAgendaItems()

        self._service(
            sessions, _FakeContentChangeLogs(), agenda_items=agenda_items
        ).apply(
            session_id=_SESSION_PK,
            event_id=_EVENT_PK,
            user_id=3,
            data=SessionContentEditData(update={"duration": "PT2H"}),
        )

        assert sessions.updates == {_SESSION_PK: {"duration": "PT2H"}}
        assert not agenda_items.updates

    def test_revert_refuses_a_change_that_is_no_longer_the_latest(self):
        stale = _content_log(
            pk=1, changes=[{"field": "title", "field_id": None, "old": "A", "new": "B"}]
        )
        newest = _content_log(
            pk=2, changes=[{"field": "title", "field_id": None, "old": "B", "new": "C"}]
        )
        sessions = _FakeSessions(_session_dto())
        logs = _FakeContentChangeLogs(stale, newest)

        with pytest.raises(ContentChangeNotLatestError):
            self._service(sessions, logs).revert(
                event_pk=_EVENT_PK, log_pk=1, user_pk=None
            )

        assert not sessions.updates
        assert not logs.created

    def test_revert_refuses_a_change_with_nothing_restorable(self):
        # A cover upload's old binary is gone and m2m entries are logged as
        # names, so neither can be written back.
        log = _content_log(
            changes=[
                {
                    "field": "cover_image",
                    "field_id": None,
                    "old": "http://img/old.png",
                    "new": "(updated)",
                },
                {"field": "facilitators", "field_id": None, "old": "Bob", "new": "Al"},
                {"field": "category", "field_id": None, "old": "RPG", "new": "Talk"},
            ]
        )
        sessions = _FakeSessions(_session_dto())

        with pytest.raises(ContentChangeNotRevertibleError):
            self._service(sessions, _FakeContentChangeLogs(log)).revert(
                event_pk=_EVENT_PK, log_pk=1, user_pk=None
            )

        assert not sessions.updates

    def test_revert_writes_the_inverse_edit_as_the_newest_change(self):
        log = _content_log(
            changes=[{"field": "title", "field_id": None, "old": "Old", "new": "New"}]
        )
        sessions = _FakeSessions(_session_dto(title="New"))
        logs = _FakeContentChangeLogs(log)

        self._service(sessions, logs).revert(event_pk=_EVENT_PK, log_pk=1, user_pk=3)

        assert sessions.updates == {_SESSION_PK: {"title": "Old"}}
        assert [change["changes"] for change in logs.created] == [
            [{"field": "title", "field_id": None, "old": "New", "new": "Old"}]
        ]

    def test_session_history_lists_only_that_sessions_changes(self):
        mine = _content_log(pk=1, changes=[])
        other = _content_log(pk=2, session_id=_SESSION_PK + 1, changes=[])
        sessions = _FakeSessions(_session_dto())
        service = self._service(sessions, _FakeContentChangeLogs(mine, other))

        title, logs = service.session_history(
            event_id=_EVENT_PK, session_id=_SESSION_PK
        )

        assert title == "My Session"
        assert logs == [mine]

    def test_list_log_returns_the_events_changes(self):
        mine = _content_log(pk=1, changes=[])
        foreign = _content_log(pk=2, event_id=_EVENT_PK + 1, changes=[])
        service = self._service(_FakeSessions(), _FakeContentChangeLogs(mine, foreign))

        assert service.list_log(_EVENT_PK) == [mine]

    def test_list_field_names_maps_pk_to_current_name(self):
        session_fields = MagicMock()
        session_fields.list_by_event.return_value = [
            SimpleNamespace(pk=7, name="System"),
            SimpleNamespace(pk=8, name="Diet"),
        ]
        service = self._service(
            _FakeSessions(), _FakeContentChangeLogs(), session_fields=session_fields
        )

        assert service.list_field_names(_EVENT_PK) == {7: "System", 8: "Diet"}

    def test_revertible_pks_are_the_latest_restorable_change_per_session(self):
        title_change = [{"field": "title", "field_id": None, "old": "A", "new": "B"}]
        cover_change = [
            {"field": "cover_image", "field_id": None, "old": "", "new": "(updated)"}
        ]
        superseded = _content_log(pk=1, changes=title_change)
        latest = _content_log(pk=2, changes=title_change)
        latest_but_stuck = _content_log(
            pk=3, session_id=_SESSION_PK + 1, changes=cover_change
        )
        logs = [superseded, latest, latest_but_stuck]
        service = self._service(_FakeSessions(), _FakeContentChangeLogs(*logs))

        assert service.revertible_log_pks(_EVENT_PK, logs) == {2}
