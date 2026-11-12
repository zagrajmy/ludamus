from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from ludamus.mills.sessions import SessionContentEditService, SessionSelfEditService
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.fields import SessionFieldValueData
from ludamus.pacts.sessions import SessionEditNotAllowedError
from ludamus.pacts.sphere import SiteDTO, SphereDTO
from tests.unit.factories import FakeTransaction, event_dto, session_dto

_SESSION_PK = 5
_EVENT_PK = 7
_SPHERE_PK = 3
_USER_PK = 10


class _FakeSessions:
    def __init__(self, session, event):
        self.rows = {session.pk: session}
        self.event = event
        self.updates: dict[int, dict] = {}
        self.field_values: list = []
        self.saved_field_values: list = []
        self.facilitators: list = []

    def read(self, pk):
        try:
            return self.rows[pk]
        except KeyError:
            raise NotFoundError from None

    def read_event(self, session_id):
        self.read(session_id)
        if self.event is None:
            raise NotFoundError
        return self.event

    def update(self, pk, data):
        self.updates.setdefault(pk, {}).update(data)

    def read_field_values(self, session_id):
        self.read(session_id)
        return list(self.field_values)

    def save_field_values(self, session_id, values):
        self.saved_field_values.append((session_id, values))

    def read_facilitators(self, session_id):
        self.read(session_id)
        return list(self.facilitators)


class _FakeSpheres:
    def __init__(self, sphere):
        self.rows = {sphere.pk: sphere}

    def read(self, pk):
        return self.rows[pk]


class _FakeSessionFields:
    def __init__(self, *fields):
        self.rows = list(fields)

    def list_by_event(self, event_id):
        return [field for field in self.rows if field.event_id == event_id]


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


class _FakeContentChangeLogs:
    def __init__(self):
        self.created: list = []

    def create(self, data):
        self.created.append(data)


class _FakePromotion:
    def __init__(self):
        self.filled: list[int] = []

    def fill_freed_seats(self, *, session_id):
        self.filled.append(session_id)


def _build(
    *, presenter_id, event_override, sphere_default, duration="", participants_limit=0
):
    sessions = _FakeSessions(
        session_dto(
            pk=_SESSION_PK,
            presenter_id=presenter_id,
            duration=duration,
            participants_limit=participants_limit,
        ),
        event_dto(
            pk=_EVENT_PK,
            sphere_id=_SPHERE_PK,
            allow_facilitator_session_edit=event_override,
        ),
    )
    sphere = SphereDTO(
        allow_facilitator_session_edit=sphere_default,
        name="Sphere",
        pk=_SPHERE_PK,
        site=SiteDTO(domain="example.com", name="Example", pk=1),
    )
    world = SimpleNamespace(
        sessions=sessions,
        session_fields=_FakeSessionFields(),
        agenda_items=_FakeAgendaItems(),
        logs=_FakeContentChangeLogs(),
        promotion=_FakePromotion(),
    )
    content_edit = SessionContentEditService(
        transaction=FakeTransaction(),
        sessions=sessions,
        session_fields=world.session_fields,
        content_change_logs=world.logs,
        agenda_items=world.agenda_items,
        waitlist_promotion=world.promotion,
    )
    world.service = SessionSelfEditService(
        sessions, world.session_fields, _FakeSpheres(sphere), content_edit
    )
    return world


class TestUpdate:
    def test_duration_change_resizes_the_scheduled_block(self):
        # The block tracks the session's length whoever edits it: a facilitator
        # shrinking their own session must not leave the grid drawing the old
        # one for the organizer to notice by hand.
        world = _build(
            presenter_id=_USER_PK,
            event_override=None,
            sphere_default=True,
            duration="PT1H",
        )
        world.agenda_items.rows[3] = SimpleNamespace(
            pk=3,
            session_id=_SESSION_PK,
            start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
        )

        world.service.update(
            session_id=_SESSION_PK,
            user_id=_USER_PK,
            data={"title": "T", "facilitator_name": "D", "duration": "PT2H"},
            field_values=[],
        )

        assert world.sessions.updates[_SESSION_PK]["duration"] == "PT2H"
        assert world.agenda_items.updates == {
            3: {"end_time": datetime(2026, 1, 1, 12, 0, tzinfo=UTC)}
        }

    def test_every_submitted_value_is_written_and_logged(self):
        world = _build(presenter_id=_USER_PK, event_override=None, sphere_default=True)
        answer = SessionFieldValueData(
            session_id=_SESSION_PK, field_id=4, value="Pathfinder"
        )

        world.service.update(
            session_id=_SESSION_PK,
            user_id=_USER_PK,
            data={
                "title": "T",
                "facilitator_name": "D",
                "description": "About",
                "contact_email": "d@example.com",
                "participants_limit": 4,
                "min_age": 12,
                "duration": "PT2H",
            },
            field_values=[answer],
        )

        assert world.sessions.updates == {
            _SESSION_PK: {
                "title": "T",
                "facilitator_name": "D",
                "description": "About",
                "contact_email": "d@example.com",
                "contact_language": "",
                "participants_limit": 4,
                "min_age": 12,
                "duration": "PT2H",
            }
        }
        assert world.sessions.saved_field_values == [(_SESSION_PK, [answer])]
        assert world.logs.created == [
            {
                "event_id": _EVENT_PK,
                "session_id": _SESSION_PK,
                "user_id": _USER_PK,
                "changes": [
                    {"field": "title", "field_id": None, "old": "Session", "new": "T"},
                    {
                        "field": "facilitator_name",
                        "field_id": None,
                        "old": "",
                        "new": "D",
                    },
                    {
                        "field": "description",
                        "field_id": None,
                        "old": "",
                        "new": "About",
                    },
                    {
                        "field": "contact_email",
                        "field_id": None,
                        "old": "",
                        "new": "d@example.com",
                    },
                    {"field": "duration", "field_id": None, "old": "", "new": "PT2H"},
                    {
                        "field": "participants_limit",
                        "field_id": None,
                        "old": 0,
                        "new": 4,
                    },
                    {"field": "min_age", "field_id": None, "old": 0, "new": 12},
                    {"field": "", "field_id": 4, "old": None, "new": "Pathfinder"},
                ],
            }
        ]

    def test_raising_the_limit_seats_waiters(self):
        # The organizer's edit always did; the presenter's own edit of the same
        # field must not leave the freed seats empty.
        world = _build(
            presenter_id=_USER_PK,
            event_override=None,
            sphere_default=True,
            participants_limit=4,
        )

        world.service.update(
            session_id=_SESSION_PK,
            user_id=_USER_PK,
            data={"title": "T", "participants_limit": 6},
            field_values=None,
        )

        assert world.promotion.filled == [_SESSION_PK]

    def test_lowering_the_limit_seats_nobody(self):
        world = _build(
            presenter_id=_USER_PK,
            event_override=None,
            sphere_default=True,
            participants_limit=4,
        )

        world.service.update(
            session_id=_SESSION_PK,
            user_id=_USER_PK,
            data={"title": "T", "participants_limit": 3},
            field_values=None,
        )

        assert not world.promotion.filled

    def test_a_presenter_cannot_move_their_session_to_another_category(self):
        world = _build(presenter_id=_USER_PK, event_override=None, sphere_default=True)

        world.service.update(
            session_id=_SESSION_PK,
            user_id=_USER_PK,
            data={"title": "T", "category_id": 99},
            field_values=None,
        )

        assert world.sessions.updates == {_SESSION_PK: {"title": "T"}}

    def test_a_stranger_may_not_edit(self):
        world = _build(presenter_id=_USER_PK, event_override=True, sphere_default=False)

        with pytest.raises(SessionEditNotAllowedError):
            world.service.update(
                session_id=_SESSION_PK,
                user_id=_USER_PK + 1,
                data={"title": "T"},
                field_values=None,
            )

        assert not world.sessions.updates
        assert not world.promotion.filled

    def test_event_may_switch_self_edit_off(self):
        world = _build(presenter_id=_USER_PK, event_override=False, sphere_default=True)

        with pytest.raises(SessionEditNotAllowedError):
            world.service.update(
                session_id=_SESSION_PK,
                user_id=_USER_PK,
                data={"title": "T"},
                field_values=None,
            )

        assert not world.sessions.updates


class TestGetEditContext:
    def test_pairs_each_field_with_the_sessions_answer(self):
        world = _build(presenter_id=_USER_PK, event_override=None, sphere_default=True)
        system = SimpleNamespace(slug="system", event_id=_EVENT_PK)
        diet = SimpleNamespace(slug="diet", event_id=_EVENT_PK)
        world.session_fields.rows = [
            system,
            diet,
            SimpleNamespace(slug="other", event_id=_EVENT_PK + 1),
        ]
        world.sessions.field_values = [
            SimpleNamespace(field_slug="system", value="Pathfinder")
        ]
        world.sessions.facilitators = [SimpleNamespace(display_name="Bob")]

        context = world.service.get_edit_context(_SESSION_PK, _USER_PK)

        assert context.session is world.sessions.rows[_SESSION_PK]
        assert context.event is world.sessions.event
        assert context.session_fields == [(system, "Pathfinder"), (diet, None)]
        assert context.facilitators == world.sessions.facilitators

    def test_anonymous_viewer_is_refused(self):
        world = _build(presenter_id=_USER_PK, event_override=None, sphere_default=True)

        with pytest.raises(SessionEditNotAllowedError):
            world.service.get_edit_context(_SESSION_PK, None)

    def test_missing_session_is_refused(self):
        world = _build(presenter_id=_USER_PK, event_override=None, sphere_default=True)

        with pytest.raises(SessionEditNotAllowedError):
            world.service.get_edit_context(_SESSION_PK + 1, _USER_PK)

    def test_someone_elses_session_is_refused(self):
        world = _build(presenter_id=_USER_PK, event_override=None, sphere_default=True)

        with pytest.raises(SessionEditNotAllowedError):
            world.service.get_edit_context(_SESSION_PK, _USER_PK + 1)

    def test_session_without_an_event_is_refused(self):
        world = _build(presenter_id=_USER_PK, event_override=None, sphere_default=True)
        world.sessions.event = None

        with pytest.raises(SessionEditNotAllowedError):
            world.service.get_edit_context(_SESSION_PK, _USER_PK)

    def test_event_may_switch_self_edit_off(self):
        world = _build(presenter_id=_USER_PK, event_override=False, sphere_default=True)

        with pytest.raises(SessionEditNotAllowedError):
            world.service.get_edit_context(_SESSION_PK, _USER_PK)
