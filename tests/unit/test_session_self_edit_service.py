from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock

from ludamus.mills.chronology import SessionContentEditService, SessionSelfEditService


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
    return service, sessions, transaction, agenda_items


class TestUpdate:
    def test_duration_change_resizes_the_scheduled_block(self):
        # The block tracks the session's length whoever edits it: a facilitator
        # shrinking their own session must not leave the grid drawing the old
        # one for the organizer to notice by hand.
        service, sessions, _, agenda_items = _build(
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
