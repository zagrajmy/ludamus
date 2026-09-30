from ludamus.mills.session_modal import SessionModalService
from tests.unit.factories import FakeTransaction


class FakeSessions:
    # (event_id, session_id) -> the modal the repository would assemble; the
    # service passes it through untouched, so a marker stands in for the DTO.
    def __init__(self, modals):
        self.modals = modals

    def read_modal(self, *, event_id, session_id, viewer_user_ids, editor_user_id):
        del viewer_user_ids, editor_user_id
        return self.modals.get((event_id, session_id))


def _service(repo):
    return SessionModalService(transaction=FakeTransaction(), sessions=repo)


class TestSessionModalService:
    def test_returns_the_modal_of_a_session_in_the_event(self):
        modal = object()
        service = _service(FakeSessions({(1, 7): modal}))

        read = service.read(
            event_id=1, session_id=7, viewer_user_ids=[], editor_user_id=None
        )

        assert read is modal

    def test_a_session_from_another_event_is_not_found(self):
        service = _service(FakeSessions({(1, 7): object()}))

        read = service.read(
            event_id=2, session_id=7, viewer_user_ids=[5], editor_user_id=5
        )

        assert read is None
