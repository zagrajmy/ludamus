from datetime import UTC, datetime

from ludamus.mills.safety import EventBanService, ShadowbanService
from ludamus.pacts.safety import (
    EventBanDTO,
    ShadowbanEventSignupDTO,
    ShadowbanHitDTO,
    ShadowbanSignupNotification,
)
from tests.unit.factories import FakeTransaction

_PRESENTER_ID = 7
_OTHER_PRESENTER_ID = 8
_SESSION_ID = 42
_NOW = datetime(2026, 3, 1, 12, tzinfo=UTC)
_USER_ID_BY_SLUG = {"bob": 2, "alice": 3}
_SLUG_BY_USER_ID = {pk: slug for slug, pk in _USER_ID_BY_SLUG.items()}


class FakeRepo:
    def __init__(self, *, signup):
        self._signup = signup
        self.bans = set()
        self.signup_reads = 0
        self.ignore_filter = False

    def read_event_signup(self, *, signed_up_ids, **_kwargs):
        self.signup_reads += 1
        if self._signup is None:
            return None
        return ShadowbanEventSignupDTO(
            event_slug=self._signup.event_slug,
            event_name=self._signup.event_name,
            session_title=self._signup.session_title,
            sphere_domain=self._signup.sphere_domain,
            hits=[
                h
                for h in self._signup.hits
                if self.ignore_filter or h.banned_user_id in signed_up_ids
            ],
        )

    @staticmethod
    def list_candidates(owner_id):
        _ = owner_id
        return []

    def banned_user_ids(self, owner_id):
        return {
            _USER_ID_BY_SLUG[slug] for owner, slug in self.bans if owner == owner_id
        }

    def banning_owner_ids(self, target_id):
        slug = _SLUG_BY_USER_ID[target_id]
        return {owner for owner, banned in self.bans if banned == slug}

    def set_shadowban(self, *, owner_id, target_slug, banned):
        if banned:
            self.bans.add((owner_id, target_slug))
        else:
            self.bans.discard((owner_id, target_slug))

    def shadowban_by_identifier(self, *, owner_id, identifier):
        if identifier not in _USER_ID_BY_SLUG:
            return False
        self.bans.add((owner_id, identifier))
        return True

    @staticmethod
    def list_session_shadowbanned(*, viewer_id, session_id):
        _ = (viewer_id, session_id)
        return []


class FakeNotifier:
    def __init__(self):
        self.signups = []

    def notify_shadowbanned_signup(self, notification):
        self.signups.append(notification)


def _service(repo, notifier=None):
    return ShadowbanService(FakeTransaction(), repo, notifier or FakeNotifier())


def _hit(recipient_id, banned_user_id):
    return ShadowbanHitDTO(
        recipient_id=recipient_id, banned_user_id=banned_user_id, in_session=False
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
        signup=_signup(_hit(_PRESENTER_ID, 2), _hit(_OTHER_PRESENTER_ID, 3))
    )
    notifier = FakeNotifier()
    service = _service(repo, notifier)

    service.notify_signups(session_id=_SESSION_ID, signed_up=[(2, "Bob"), (3, "Alice")])

    recipients = {
        (n.recipient_user_id, tuple(n.player_names)) for n in notifier.signups
    }
    assert recipients == {(_PRESENTER_ID, ("Bob",)), (_OTHER_PRESENTER_ID, ("Alice",))}


def test_notify_signups_dedupes_repeated_user_id():
    repo = FakeRepo(signup=_signup(_hit(_PRESENTER_ID, 2), _hit(_PRESENTER_ID, 2)))
    notifier = FakeNotifier()
    service = _service(repo, notifier)

    service.notify_signups(session_id=_SESSION_ID, signed_up=[(2, "Bob")])

    assert len(notifier.signups) == 1
    assert notifier.signups[0].player_names == ["Bob"]


def test_notify_signups_reports_distinct_users_sharing_a_name():
    repo = FakeRepo(signup=_signup(_hit(_PRESENTER_ID, 2), _hit(_PRESENTER_ID, 3)))
    notifier = FakeNotifier()
    service = _service(repo, notifier)

    service.notify_signups(session_id=_SESSION_ID, signed_up=[(2, "Bob"), (3, "Bob")])

    assert notifier.signups[0].player_names == ["Bob", "Bob"]


def test_notify_signups_skips_a_hit_for_a_player_not_in_the_signup():
    # The repo may return hits for a banned id the caller did not name; with
    # no display name to report, the recipient gets nothing.
    repo = FakeRepo(signup=_signup(_hit(_PRESENTER_ID, 2)))
    repo.ignore_filter = True
    notifier = FakeNotifier()

    _service(repo, notifier).notify_signups(
        session_id=_SESSION_ID, signed_up=[(9, "Zed")]
    )

    assert not notifier.signups


def test_notify_signups_splits_event_and_session_players():
    repo = FakeRepo(
        signup=_signup(
            _hit(_PRESENTER_ID, 2),
            ShadowbanHitDTO(
                recipient_id=_PRESENTER_ID, banned_user_id=3, in_session=True
            ),
        )
    )
    notifier = FakeNotifier()

    _service(repo, notifier).notify_signups(
        session_id=_SESSION_ID, signed_up=[(2, "Bob"), (3, "Alice")]
    )

    assert notifier.signups == [
        ShadowbanSignupNotification(
            recipient_user_id=_PRESENTER_ID,
            event_slug="con-2026",
            event_name="Con 2026",
            session_title="Deniable Game",
            sphere_domain="con.example.net",
            player_names=["Bob"],
            session_player_names=["Alice"],
        )
    ]


def test_notify_signups_with_nobody_signed_up_is_a_noop():
    repo = FakeRepo(signup=_signup(_hit(_PRESENTER_ID, 2)))
    notifier = FakeNotifier()

    _service(repo, notifier).notify_signups(session_id=_SESSION_ID, signed_up=[])

    assert not notifier.signups
    assert repo.signup_reads == 0


def test_notify_signups_without_hits_or_session_is_a_noop():
    notifier = FakeNotifier()

    _service(FakeRepo(signup=None), notifier).notify_signups(
        session_id=_SESSION_ID, signed_up=[(2, "Bob")]
    )
    _service(FakeRepo(signup=_signup()), notifier).notify_signups(
        session_id=_SESSION_ID, signed_up=[(2, "Bob")]
    )

    assert not notifier.signups


def test_read_methods_pass_through_the_repo():
    repo = FakeRepo(signup=None)
    repo.bans = {(_PRESENTER_ID, "bob"), (_OTHER_PRESENTER_ID, "bob")}
    service = _service(repo)

    assert service.list_candidates(_PRESENTER_ID) == []
    assert service.banned_user_ids(_PRESENTER_ID) == {_USER_ID_BY_SLUG["bob"]}
    assert service.banning_owner_ids(_USER_ID_BY_SLUG["bob"]) == {
        _PRESENTER_ID,
        _OTHER_PRESENTER_ID,
    }
    assert (
        service.list_session_warnings(viewer_id=_PRESENTER_ID, session_id=_SESSION_ID)
        == []
    )


def test_set_shadowban_toggles_the_row():
    repo = FakeRepo(signup=None)
    service = _service(repo)

    service.set_shadowban(owner_id=_PRESENTER_ID, target_slug="bob", banned=True)
    assert repo.bans == {(_PRESENTER_ID, "bob")}

    service.set_shadowban(owner_id=_PRESENTER_ID, target_slug="bob", banned=False)
    assert repo.bans == set()


def test_add_by_identifier_rejects_blank_input_without_touching_the_repo():
    repo = FakeRepo(signup=None)

    assert (
        _service(repo).add_by_identifier(owner_id=_PRESENTER_ID, identifier="  ")
        is False
    )
    assert repo.bans == set()


def test_add_by_identifier_strips_and_reports_the_repo_answer():
    repo = FakeRepo(signup=None)
    service = _service(repo)

    assert service.add_by_identifier(owner_id=_PRESENTER_ID, identifier=" bob ") is True
    assert (
        service.add_by_identifier(owner_id=_PRESENTER_ID, identifier="nobody") is False
    )
    assert repo.bans == {(_PRESENTER_ID, "bob")}


class FakeEventBans:
    def __init__(self):
        self.rows = {}
        self._next = 1

    def list_by_event(self, event_id):
        return [ban for (event, _), ban in self.rows.items() if event == event_id]

    def is_banned(self, *, event_id, user_id):
        return any(
            event == event_id and ban.user_slug == _SLUG_BY_USER_ID.get(user_id)
            for (event, _), ban in self.rows.items()
        )

    def banned_event_ids(self, *, event_ids, user_id):
        return {e for e in event_ids if self.is_banned(event_id=e, user_id=user_id)}

    def ban(self, *, event_id, identifier, reason):
        if identifier not in _USER_ID_BY_SLUG:
            return False
        self.rows[event_id, self._next] = EventBanDTO(
            pk=self._next,
            user_name=identifier.title(),
            user_slug=identifier,
            reason=reason,
            created_at=_NOW,
        )
        self._next += 1
        return True

    def unban(self, *, event_id, ban_id):
        del self.rows[event_id, ban_id]


def _event_ban_service():
    repo = FakeEventBans()
    return EventBanService(FakeTransaction(), repo), repo


def test_event_ban_rejects_blank_identifier():
    service, repo = _event_ban_service()

    assert service.ban(event_id=1, identifier="   ", reason="x") is False
    assert not repo.rows


def test_event_ban_unknown_identifier_reports_failure():
    service, _ = _event_ban_service()

    assert service.ban(event_id=1, identifier="nobody", reason="x") is False


def test_event_ban_strips_input_and_scopes_reads_to_the_event():
    service, _ = _event_ban_service()

    assert service.ban(event_id=1, identifier=" bob ", reason=" spam ") is True

    [ban] = service.list_for_event(1)
    assert (ban.user_slug, ban.reason) == ("bob", "spam")
    assert service.list_for_event(2) == []
    assert service.is_banned(event_id=1, user_id=_USER_ID_BY_SLUG["bob"]) is True
    assert service.is_banned(event_id=2, user_id=_USER_ID_BY_SLUG["bob"]) is False
    assert service.banned_event_ids(
        event_ids={1, 2}, user_id=_USER_ID_BY_SLUG["bob"]
    ) == {1}


def test_event_unban_removes_the_row():
    service, repo = _event_ban_service()
    service.ban(event_id=1, identifier="bob", reason="")
    [ban] = service.list_for_event(1)

    service.unban(event_id=1, ban_id=ban.pk)

    assert not repo.rows
