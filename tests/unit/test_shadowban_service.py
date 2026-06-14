from contextlib import contextmanager

from ludamus.mills.safety import ShadowbanService
from ludamus.pacts.safety import (
    ShadowbanCandidateDTO,
    ShadowbanEventContextDTO,
    ShadowbanHitDTO,
)

_PRESENTER_ID = 7
_OTHER_PRESENTER_ID = 8
_SESSION_ID = 42


@contextmanager
def _atomic():
    yield


class FakeTransaction:
    @staticmethod
    def atomic():
        return _atomic()


class FakeRepo:
    def __init__(self, *, candidates=None, context=None, hits=None):
        self._candidates = list(candidates or [])
        self._context = context
        self._hits = list(hits or [])
        self.set_calls: list[tuple[int, str, bool]] = []
        self.identifier_calls: list[tuple[int, str]] = []
        self.found = True

    def list_candidates(self, _owner_id):
        return self._candidates

    def set_shadowban(self, *, owner_id, target_slug, banned):
        self.set_calls.append((owner_id, target_slug, banned))

    def shadowban_by_identifier(self, *, owner_id, identifier):
        self.identifier_calls.append((owner_id, identifier))
        return self.found

    def read_event_context(self, _session_id):
        return self._context

    def event_shadowban_hits(self, *, signed_up_ids, **_kwargs):
        return [h for h in self._hits if h.banned_user_id in signed_up_ids]


class FakeNotifier:
    def __init__(self):
        self.signups = []

    def notify_shadowbanned_signup(self, notification):
        self.signups.append(notification)


def _service(repo, notifier=None):
    return ShadowbanService(FakeTransaction(), repo, notifier or FakeNotifier())


def _context():
    return ShadowbanEventContextDTO(event_slug="con-2026", event_name="Con 2026")


def _hit(presenter_id, email, banned_user_id):
    return ShadowbanHitDTO(
        presenter_id=presenter_id, presenter_email=email, banned_user_id=banned_user_id
    )


def test_list_candidates_passes_through():
    # Arrange
    candidate = ShadowbanCandidateDTO(
        pk=1, name="Bob", slug="bob", is_shadowbanned=True
    )
    service = _service(FakeRepo(candidates=[candidate]))

    # Act
    result = service.list_candidates(_PRESENTER_ID)

    # Assert
    assert result == [candidate]


def test_set_shadowban_delegates_to_repo():
    # Arrange
    repo = FakeRepo()
    service = _service(repo)

    # Act
    service.set_shadowban(owner_id=_PRESENTER_ID, target_slug="bob", banned=True)

    # Assert
    assert repo.set_calls == [(_PRESENTER_ID, "bob", True)]


def test_add_by_identifier_trims_and_returns_found():
    # Arrange
    repo = FakeRepo()
    service = _service(repo)

    # Act
    found = service.add_by_identifier(owner_id=_PRESENTER_ID, identifier="  bob  ")

    # Assert
    assert found is True
    assert repo.identifier_calls == [(_PRESENTER_ID, "bob")]


def test_add_by_identifier_rejects_blank():
    # Arrange
    repo = FakeRepo()
    service = _service(repo)

    # Act
    found = service.add_by_identifier(owner_id=_PRESENTER_ID, identifier="   ")

    # Assert
    assert found is False
    assert not repo.identifier_calls


def test_notify_signups_emails_presenter_about_banned_players():
    # Arrange
    repo = FakeRepo(context=_context(), hits=[_hit(_PRESENTER_ID, "gm@example.com", 2)])
    notifier = FakeNotifier()
    service = _service(repo, notifier)

    # Act
    service.notify_signups(session_id=_SESSION_ID, signed_up=[(2, "Bob"), (3, "Alice")])

    # Assert
    assert len(notifier.signups) == 1
    notification = notifier.signups[0]
    assert notification.recipient_user_id == _PRESENTER_ID
    assert notification.recipient_email == "gm@example.com"
    assert notification.event_slug == "con-2026"
    assert notification.player_names == ["Bob"]


def test_notify_signups_notifies_every_banner_in_the_event():
    # Arrange: two presenters in the event each shadowbanned a different player.
    repo = FakeRepo(
        context=_context(),
        hits=[
            _hit(_PRESENTER_ID, "gm@example.com", 2),
            _hit(_OTHER_PRESENTER_ID, "other@example.com", 3),
        ],
    )
    notifier = FakeNotifier()
    service = _service(repo, notifier)

    # Act
    service.notify_signups(session_id=_SESSION_ID, signed_up=[(2, "Bob"), (3, "Alice")])

    # Assert
    recipients = {
        (n.recipient_user_id, tuple(n.player_names)) for n in notifier.signups
    }
    assert recipients == {(_PRESENTER_ID, ("Bob",)), (_OTHER_PRESENTER_ID, ("Alice",))}


def test_notify_signups_silent_when_no_banned_players():
    # Arrange
    repo = FakeRepo(context=_context(), hits=[])
    notifier = FakeNotifier()
    service = _service(repo, notifier)

    # Act
    service.notify_signups(session_id=_SESSION_ID, signed_up=[(2, "Bob")])

    # Assert
    assert not notifier.signups


def test_notify_signups_silent_when_no_signups():
    # Arrange
    repo = FakeRepo(context=_context(), hits=[_hit(_PRESENTER_ID, "gm@example.com", 2)])
    notifier = FakeNotifier()
    service = _service(repo, notifier)

    # Act
    service.notify_signups(session_id=_SESSION_ID, signed_up=[])

    # Assert
    assert not notifier.signups


def test_notify_signups_silent_when_session_has_no_event():
    # Arrange
    repo = FakeRepo(context=None, hits=[_hit(_PRESENTER_ID, "gm@example.com", 2)])
    notifier = FakeNotifier()
    service = _service(repo, notifier)

    # Act
    service.notify_signups(session_id=_SESSION_ID, signed_up=[(2, "Bob")])

    # Assert
    assert not notifier.signups
