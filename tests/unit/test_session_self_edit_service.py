from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from ludamus.mills.chronology import (
    SessionContentEditService,
    SessionEditNotAllowedError,
    SessionSelfEditService,
)
from ludamus.pacts import NotFoundError


class _FakeUpload:
    name = "cover.png"

    def read(self) -> bytes:
        return b""


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
    content_edit = SessionContentEditService(
        transaction, sessions, session_fields, MagicMock()
    )
    service = SessionSelfEditService(sessions, session_fields, spheres, content_edit)
    return service, sessions, transaction


class TestCanEdit:
    def test_owner_with_effective_true(self):
        service, _, _ = _build(
            presenter_id=10, event_override=None, sphere_default=True
        )
        assert service.can_edit(5, 10) is True

    def test_anonymous_user_id_none(self):
        service, _, _ = _build(
            presenter_id=10, event_override=None, sphere_default=True
        )
        assert service.can_edit(5, None) is False

    def test_non_owner(self):
        service, _, _ = _build(
            presenter_id=10, event_override=None, sphere_default=True
        )
        assert service.can_edit(5, 99) is False

    def test_event_override_false_blocks_owner(self):
        service, _, _ = _build(
            presenter_id=10, event_override=False, sphere_default=True
        )
        assert service.can_edit(5, 10) is False

    def test_sphere_default_false_blocks_owner(self):
        service, _, _ = _build(
            presenter_id=10, event_override=None, sphere_default=False
        )
        assert service.can_edit(5, 10) is False

    def test_event_override_true_beats_sphere_false(self):
        service, _, _ = _build(
            presenter_id=10, event_override=True, sphere_default=False
        )
        assert service.can_edit(5, 10) is True

    def test_placeholder_presenter_none_never_editable(self):
        service, _, _ = _build(
            presenter_id=None, event_override=None, sphere_default=True
        )
        assert service.can_edit(5, 10) is False

    def test_missing_session_returns_false(self):
        service, sessions, _ = _build(
            presenter_id=10, event_override=None, sphere_default=True
        )
        sessions.read.side_effect = NotFoundError
        assert service.can_edit(5, 10) is False

    def test_unresolvable_event_returns_false(self):
        service, sessions, _ = _build(
            presenter_id=10, event_override=None, sphere_default=True
        )
        sessions.read_event.side_effect = NotFoundError
        assert service.can_edit(5, 10) is False


class TestUpdate:
    def test_writes_session_and_field_values_atomically(self):
        service, sessions, transaction = _build(
            presenter_id=10, event_override=None, sphere_default=True
        )
        field_values = [{"session_id": 5, "field_id": 1, "value": "x"}]

        service.update(
            5,
            10,
            {"title": "T", "display_name": "D", "participants_limit": 4},
            field_values,
        )

        transaction.atomic.assert_called_once()
        sessions.update.assert_called_once_with(
            5,
            {
                "title": "T",
                "display_name": "D",
                "description": "",
                "requirements": "",
                "needs": "",
                "contact_email": "",
                "participants_limit": 4,
                "min_age": 0,
                "duration": "",
            },
        )
        sessions.save_field_values.assert_called_once_with(5, field_values)

    def test_passes_uploaded_cover_image_through(self):
        service, sessions, _ = _build(
            presenter_id=10, event_override=None, sphere_default=True
        )
        cover = _FakeUpload()

        service.update(
            5, 10, {"title": "T", "display_name": "D", "cover_image": cover}, []
        )

        assert sessions.update.call_args.args[1]["cover_image"] is cover

    def test_clears_cover_image_when_false(self):
        service, sessions, _ = _build(
            presenter_id=10, event_override=None, sphere_default=True
        )

        service.update(
            5, 10, {"title": "T", "display_name": "D", "cover_image": False}, []
        )

        sessions.update.assert_called_once_with(
            5,
            {
                "title": "T",
                "display_name": "D",
                "description": "",
                "requirements": "",
                "needs": "",
                "contact_email": "",
                "participants_limit": 0,
                "min_age": 0,
                "duration": "",
                "cover_image": "",
            },
        )

    def test_leaves_cover_image_untouched_when_absent(self):
        service, sessions, _ = _build(
            presenter_id=10, event_override=None, sphere_default=True
        )

        service.update(5, 10, {"title": "T", "display_name": "D"}, [])

        assert "cover_image" not in sessions.update.call_args.args[1]

    def test_raises_when_not_allowed(self):
        service, sessions, _ = _build(
            presenter_id=10, event_override=False, sphere_default=True
        )

        with pytest.raises(SessionEditNotAllowedError):
            service.update(5, 10, {"title": "T", "display_name": "D"}, [])

        sessions.update.assert_not_called()
