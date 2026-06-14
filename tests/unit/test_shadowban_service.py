from contextlib import contextmanager

from ludamus.mills.safety import ShadowbanService
from ludamus.pacts.safety import ShadowbanCandidateDTO, ShadowbanSignupTargetDTO

_PRESENTER_ID = 7
_SESSION_ID = 42


@contextmanager
def _atomic():
    yield


class FakeTransaction:
    @staticmethod
    def atomic():
        return _atomic()


class FakeRepo:
    def __init__(self, *, candidates=None, banned_ids=None, target=None):
        self._candidates = list(candidates or [])
        self._banned_ids = set(banned_ids or set())
        self._target = target
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

    def shadowbanned_user_ids(self, _owner_id):
        return self._banned_ids

    def read_signup_target(self, _session_id):
        return self._target


class FakeNotifier:
    def __init__(self):
        self.signups = []

    def notify_shadowbanned_signup(self, notification):
        self.signups.append(notification)


def _service(repo, notifier=None):
    return ShadowbanService(FakeTransaction(), repo, notifier or FakeNotifier())


def _target():
    return ShadowbanSignupTargetDTO(
        presenter_id=_PRESENTER_ID,
        presenter_email="gm@example.com",
        session_title="Curse of Strahd",
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
    repo = FakeRepo(banned_ids={2}, target=_target())
    notifier = FakeNotifier()
    service = _service(repo, notifier)

    # Act
    service.notify_signups(session_id=_SESSION_ID, signed_up=[(2, "Bob"), (3, "Alice")])

    # Assert
    assert len(notifier.signups) == 1
    notification = notifier.signups[0]
    assert notification.recipient_user_id == _PRESENTER_ID
    assert notification.recipient_email == "gm@example.com"
    assert notification.session_id == _SESSION_ID
    assert notification.player_names == ["Bob"]


def test_notify_signups_silent_when_no_banned_players():
    # Arrange
    repo = FakeRepo(banned_ids={99}, target=_target())
    notifier = FakeNotifier()
    service = _service(repo, notifier)

    # Act
    service.notify_signups(session_id=_SESSION_ID, signed_up=[(2, "Bob")])

    # Assert
    assert not notifier.signups


def test_notify_signups_silent_when_no_signups():
    # Arrange
    repo = FakeRepo(banned_ids={2}, target=_target())
    notifier = FakeNotifier()
    service = _service(repo, notifier)

    # Act
    service.notify_signups(session_id=_SESSION_ID, signed_up=[])

    # Assert
    assert not notifier.signups


def test_notify_signups_silent_when_session_has_no_presenter():
    # Arrange
    repo = FakeRepo(banned_ids={2}, target=None)
    notifier = FakeNotifier()
    service = _service(repo, notifier)

    # Act
    service.notify_signups(session_id=_SESSION_ID, signed_up=[(2, "Bob")])

    # Assert
    assert not notifier.signups
