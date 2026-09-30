from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ludamus.mills.chronology import (
    SessionContentEditService,
    SessionEditNotAllowedError,
    SessionSelfEditService,
)
from ludamus.pacts import NotFoundError


@contextmanager
def _atomic():
    yield


def _build(*, presenter_id, event_override, sphere_default):
    transaction = MagicMock()
    transaction.atomic.side_effect = _atomic
    sessions = MagicMock()
    sessions.read.return_value = MagicMock(presenter_id=presenter_id)
    sessions.read_event.return_value = MagicMock(
        pk=7, sphere_id=3, allow_facilitator_session_edit=event_override
    )
    sessions.read_field_values.return_value = []
    sessions.read_facilitators.return_value = []
    session_fields = MagicMock()
    session_fields.list_by_event.return_value = []
    spheres = MagicMock()
    spheres.read.return_value = MagicMock(allow_facilitator_session_edit=sphere_default)
    agenda_items = MagicMock()
    content_edit = SessionContentEditService(
        transaction=transaction,
        sessions=sessions,
        session_fields=session_fields,
        content_change_logs=MagicMock(),
        agenda_items=agenda_items,
    )
    service = SessionSelfEditService(sessions, session_fields, spheres, content_edit)
    return service, sessions, transaction, agenda_items, session_fields


class TestUpdate:
    def test_duration_change_resizes_the_scheduled_block(self):
        # The block tracks the session's length whoever edits it: a facilitator
        # shrinking their own session must not leave the grid drawing the old
        # one for the organizer to notice by hand.
        service, sessions, _, agenda_items, _ = _build(
            presenter_id=10, event_override=None, sphere_default=True
        )
        sessions.read.return_value = MagicMock(presenter_id=10, duration="PT1H")
        agenda_items.read_by_session.return_value = MagicMock(
            pk=3, start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        )

        service.update(
            5, 10, {"title": "T", "facilitator_name": "D", "duration": "PT2H"}, []
        )

        assert sessions.update.call_args.args[1]["duration"] == "PT2H"
        agenda_items.update.assert_called_once_with(
            3, {"end_time": datetime(2026, 1, 1, 12, 0, tzinfo=UTC)}
        )

    def test_an_uploaded_cover_replaces_the_stored_one(self):
        service, sessions, _, _, _ = _build(
            presenter_id=10, event_override=True, sphere_default=False
        )
        upload = SimpleNamespace(name="cover.png", read=lambda _size=-1: b"")

        service.update(5, 10, {"title": "T", "cover_image": upload}, None)

        assert sessions.update.call_args.args[1]["cover_image"] is upload

    def test_a_stranger_may_not_edit(self):
        service, sessions, _, _, _ = _build(
            presenter_id=10, event_override=True, sphere_default=False
        )

        with pytest.raises(SessionEditNotAllowedError):
            service.update(5, 11, {"title": "T"}, None)

        sessions.update.assert_not_called()


class TestGetEditContext:
    def test_pairs_each_field_with_the_sessions_answer(self):
        service, sessions, _, _, session_fields = _build(
            presenter_id=10, event_override=None, sphere_default=True
        )
        system, diet = SimpleNamespace(slug="system"), SimpleNamespace(slug="diet")
        session_fields.list_by_event.return_value = [system, diet]
        sessions.read_field_values.return_value = [
            SimpleNamespace(field_slug="system", value="Pathfinder")
        ]

        context = service.get_edit_context(5, 10)

        assert context.session is sessions.read.return_value
        assert context.event is sessions.read_event.return_value
        assert context.session_fields == [(system, "Pathfinder"), (diet, None)]

    def test_anonymous_viewer_is_refused(self):
        service, _, _, _, _ = _build(
            presenter_id=10, event_override=None, sphere_default=True
        )

        with pytest.raises(SessionEditNotAllowedError):
            service.get_edit_context(5, None)

    def test_missing_session_is_refused(self):
        service, sessions, _, _, _ = _build(
            presenter_id=10, event_override=None, sphere_default=True
        )
        sessions.read.side_effect = NotFoundError

        with pytest.raises(SessionEditNotAllowedError):
            service.get_edit_context(5, 10)

    def test_someone_elses_session_is_refused(self):
        service, _, _, _, _ = _build(
            presenter_id=10, event_override=None, sphere_default=True
        )

        with pytest.raises(SessionEditNotAllowedError):
            service.get_edit_context(5, 11)

    def test_session_without_an_event_is_refused(self):
        service, sessions, _, _, _ = _build(
            presenter_id=10, event_override=None, sphere_default=True
        )
        sessions.read_event.side_effect = NotFoundError

        with pytest.raises(SessionEditNotAllowedError):
            service.get_edit_context(5, 10)

    def test_event_may_switch_self_edit_off(self):
        service, _, _, _, _ = _build(
            presenter_id=10, event_override=False, sphere_default=True
        )

        with pytest.raises(SessionEditNotAllowedError):
            service.get_edit_context(5, 10)
