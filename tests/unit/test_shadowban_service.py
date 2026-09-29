from contextlib import contextmanager

from ludamus.mills.safety import ShadowbanService
from ludamus.pacts.safety import ShadowbanEventSignupDTO, ShadowbanHitDTO

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
    def __init__(self, *, signup):
        self._signup = signup

    def read_event_signup(self, *, signed_up_ids, **_kwargs):
        return ShadowbanEventSignupDTO(
            event_slug=self._signup.event_slug,
            event_name=self._signup.event_name,
            session_title=self._signup.session_title,
            sphere_domain=self._signup.sphere_domain,
            hits=[h for h in self._signup.hits if h.banned_user_id in signed_up_ids],
        )


class FakeNotifier:
    def __init__(self):
        self.signups = []

    def notify_shadowbanned_signup(self, notification):
        self.signups.append(notification)


def _service(repo, notifier=None):
    return ShadowbanService(FakeTransaction(), repo, notifier or FakeNotifier())


def _hit(recipient_id, email, banned_user_id):
    return ShadowbanHitDTO(
        recipient_id=recipient_id,
        recipient_email=email,
        banned_user_id=banned_user_id,
        in_session=False,
    )


def _signup(*hits):
    return ShadowbanEventSignupDTO(
        event_slug="con-2026",
        event_name="Con 2026",
        session_title="Deniable Game",
        sphere_domain="con.example.net",
        hits=list(hits),
    )


def test_notify_signups_notifies_every_banner_in_the_event():
    repo = FakeRepo(
        signup=_signup(
            _hit(_PRESENTER_ID, "gm@example.com", 2),
            _hit(_OTHER_PRESENTER_ID, "other@example.com", 3),
        )
    )
    notifier = FakeNotifier()
    service = _service(repo, notifier)

    service.notify_signups(session_id=_SESSION_ID, signed_up=[(2, "Bob"), (3, "Alice")])

    recipients = {
        (n.recipient_user_id, tuple(n.player_names)) for n in notifier.signups
    }
    assert recipients == {(_PRESENTER_ID, ("Bob",)), (_OTHER_PRESENTER_ID, ("Alice",))}


def test_notify_signups_dedupes_repeated_user_id():
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
