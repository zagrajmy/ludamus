from contextlib import contextmanager

from ludamus.mills.safety import ShadowbanService
from ludamus.pacts.safety import (
    SessionShadowbanWarningDTO,
    ShadowbanCandidateDTO,
    ShadowbanEventSignupDTO,
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
    def __init__(self, *, candidates=None, signup=None, warnings=None):
        self._candidates = list(candidates or [])
        self._signup = signup
        self._warnings = list(warnings or [])
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

    def read_event_signup(self, *, signed_up_ids, **_kwargs):
        if self._signup is None:
            return None
        return ShadowbanEventSignupDTO(
            event_slug=self._signup.event_slug,
            event_name=self._signup.event_name,
            session_title=self._signup.session_title,
            hits=[h for h in self._signup.hits if h.banned_user_id in signed_up_ids],
        )

    def list_session_shadowbanned(self, **_kwargs):
        return self._warnings


class FakeNotifier:
    def __init__(self):
        self.signups = []

    def notify_shadowbanned_signup(self, notification):
        self.signups.append(notification)


def _service(repo, notifier=None):
    return ShadowbanService(FakeTransaction(), repo, notifier or FakeNotifier())


def _hit(recipient_id, email, banned_user_id, *, in_session=False):
    return ShadowbanHitDTO(
        recipient_id=recipient_id,
        recipient_email=email,
        banned_user_id=banned_user_id,
        in_session=in_session,
    )


def _signup(*hits):
    return ShadowbanEventSignupDTO(
        event_slug="con-2026",
        event_name="Con 2026",
        session_title="Deniable Game",
        hits=list(hits),
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


def test_list_session_warnings_passes_through():
    # Arrange
    warning = SessionShadowbanWarningDTO.model_construct(
        user=None, shadowbanned_at=None
    )
    service = _service(FakeRepo(warnings=[warning]))

    # Act
    result = service.list_session_warnings(viewer_id=_PRESENTER_ID, session_id=1)

    # Assert
    assert result == [warning]


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
    repo = FakeRepo(signup=_signup(_hit(_PRESENTER_ID, "gm@example.com", 2)))
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
    assert notification.session_player_names == []


def test_notify_signups_discerns_signup_into_recipients_session():
    repo = FakeRepo(
        signup=_signup(
            _hit(_PRESENTER_ID, "gm@example.com", 2, in_session=True),
            _hit(_PRESENTER_ID, "gm@example.com", 3),
        )
    )
    notifier = FakeNotifier()
    service = _service(repo, notifier)

    service.notify_signups(session_id=_SESSION_ID, signed_up=[(2, "Bob"), (3, "Alice")])

    assert len(notifier.signups) == 1
    notification = notifier.signups[0]
    assert notification.session_player_names == ["Bob"]
    assert notification.player_names == ["Alice"]
    assert notification.session_title == "Deniable Game"


def test_notify_signups_notifies_every_banner_in_the_event():
    # Arrange: two presenters in the event each shadowbanned a different player.
    repo = FakeRepo(
        signup=_signup(
            _hit(_PRESENTER_ID, "gm@example.com", 2),
            _hit(_OTHER_PRESENTER_ID, "other@example.com", 3),
        )
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


def test_notify_signups_dedupes_repeated_user_id():
    # Same banned user id appearing twice for one presenter -> listed once.
    repo = FakeRepo(
        signup=_signup(
            _hit(_PRESENTER_ID, "gm@example.com", 2),
            _hit(_PRESENTER_ID, "gm@example.com", 2),
        )
    )
    notifier = FakeNotifier()
    service = _service(repo, notifier)

    service.notify_signups(session_id=_SESSION_ID, signed_up=[(2, "Bob")])

    assert len(notifier.signups) == 1
    assert notifier.signups[0].player_names == ["Bob"]


def test_notify_signups_reports_distinct_users_sharing_a_name():
    # Two different banned users with the same display name must both appear.
    repo = FakeRepo(
        signup=_signup(
            _hit(_PRESENTER_ID, "gm@example.com", 2),
            _hit(_PRESENTER_ID, "gm@example.com", 3),
        )
    )
    notifier = FakeNotifier()
    service = _service(repo, notifier)

    service.notify_signups(session_id=_SESSION_ID, signed_up=[(2, "Bob"), (3, "Bob")])

    assert notifier.signups[0].player_names == ["Bob", "Bob"]


def test_notify_signups_skips_presenter_with_no_resolvable_names():
    # A hit whose player resolves to an empty name yields nothing to report,
    # so that presenter is not notified with an empty list.
    repo = FakeRepo(signup=_signup(_hit(_PRESENTER_ID, "gm@example.com", 2)))
    notifier = FakeNotifier()
    service = _service(repo, notifier)

    service.notify_signups(session_id=_SESSION_ID, signed_up=[(2, "")])

    assert not notifier.signups


def test_notify_signups_silent_when_no_banned_players():
    # Arrange
    repo = FakeRepo(signup=_signup())
    notifier = FakeNotifier()
    service = _service(repo, notifier)

    # Act
    service.notify_signups(session_id=_SESSION_ID, signed_up=[(2, "Bob")])

    # Assert
    assert not notifier.signups


def test_notify_signups_silent_when_no_signups():
    # Arrange
    repo = FakeRepo(signup=_signup(_hit(_PRESENTER_ID, "gm@example.com", 2)))
    notifier = FakeNotifier()
    service = _service(repo, notifier)

    # Act
    service.notify_signups(session_id=_SESSION_ID, signed_up=[])

    # Assert
    assert not notifier.signups


def test_notify_signups_silent_when_session_has_no_event():
    # Arrange
    repo = FakeRepo(signup=None)
    notifier = FakeNotifier()
    service = _service(repo, notifier)

    # Act
    service.notify_signups(session_id=_SESSION_ID, signed_up=[(2, "Bob")])

    # Assert
    assert not notifier.signups
