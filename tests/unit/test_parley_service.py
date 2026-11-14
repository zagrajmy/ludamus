import logging
from datetime import UTC, datetime, timedelta

import pytest

from ludamus.mills.parley import (
    ParleyReportRetentionService,
    ParleyRevocationService,
    ParleyService,
    sign_revocations,
)
from ludamus.pacts.parley import (
    REVOKE_EVERYONE,
    ParleyAccessDTO,
    ParleyCapabilityClaims,
    ParleyConversationDTO,
    ParleyConversationKind,
    ParleyMembership,
    ParleyMemberState,
    ParleyModerationResult,
    ParleyReportData,
    ParleyReportedMessage,
    ParleyReportedRef,
    ParleyRoomDTO,
    ParleyRoomKind,
    ParleyTeamSeat,
    ParleyWorkerUnavailableError,
)
from ludamus.pacts.sphere import SphereRole
from ludamus.pacts.user import AgeBand
from ludamus.specs.parley import PARLEY_PASS_MAX_LENGTH, PARLEY_TOKEN_LIFETIME

NOW = datetime(2026, 8, 6, 12, tzinfo=UTC)
EVENT_LENGTH = 10 * 3600
USER_ID = 123


class NoConversations:
    """Someone the direct and group conversations are not open to."""

    def __init__(self, conversations=()):
        self.conversations = list(conversations)

    @staticmethod
    def is_eligible(_user_id):
        return False

    @staticmethod
    def read_age_band(_user_id):
        return AgeBand.UNKNOWN

    def list_for(self, _user_id):
        return self.conversations

    def has_conversation(self, *, user_id, kinds):
        return any(conversation.kind in kinds for conversation in self.conversations)

    @staticmethod
    def list_blocked(_user_id):
        return []


class OpenConversations(NoConversations):
    @staticmethod
    def is_eligible(_user_id):
        return True


def _conversation(kind):
    return ParleyConversationDTO(
        id=f"conversation:{len(kind)}",
        kind=kind,
        title="Drużyna",
        state=ParleyMemberState.ACTIVE,
        can_write=True,
        is_admin=False,
        members=[],
    )


class Access:
    """The rooms someone is in, and the spheres whose team they are on."""

    def __init__(self, rooms=None, *, seats=(), has_rooms=False):
        self.rooms = rooms
        self.seats = [ParleyTeamSeat(sphere_id=s, role=role) for s, role in seats]
        self._has_rooms = has_rooms
        self.asked = []
        self.saved = []
        self.reported = {}
        self.resolved = []

    def list_team_seats(self, _user_id):
        return self.seats

    def read_access(self, *, user_id, window, moderated):
        self.asked.append((window.now, moderated))
        if self.rooms is None:
            return None
        return ParleyAccessDTO(
            user_id=user_id,
            user_name="Ada",
            user_avatar_url="https://example.com/ada.png",
            rooms=self.rooms,
        )

    def has_rooms(self, *, user_id, window, moderated):
        self.asked.append((window.now, moderated))
        return self._has_rooms

    def save_report(self, report):
        self.saved.append(report)

    def list_reported(self, report_ids):
        return [self.reported[pk] for pk in report_ids]

    def resolve_reports(self, *, room_id, message_id, now):
        self.resolved.append((room_id, message_id, now))


class LengthSigner:
    """A pass as long as its events make it: `per_event` characters each."""

    def __init__(self, per_event=0):
        self.per_event = per_event
        self.signed = []

    def sign(self, claims):
        self.signed.append(claims)
        return "t" * (100 + self.per_event * len(getattr(claims, "events", {})))


def _event(
    pk,
    *,
    sphere=45,
    ends_at=1_786_100_000,
    starts_at=None,
    can_write=True,
    can_moderate=False,
):
    return ParleyRoomDTO(
        kind=ParleyRoomKind.EVENT,
        sphere_id=sphere,
        pk=pk,
        title=f"Event {pk}",
        can_write=can_write,
        can_moderate=can_moderate,
        starts_at=ends_at - EVENT_LENGTH if starts_at is None else starts_at,
        ends_at=ends_at,
    )


def _session(
    pk, *, event, sphere=45, can_write=True, can_moderate=False, ends_at=1_786_000_000
):
    return ParleyRoomDTO(
        kind=ParleyRoomKind.SESSION,
        sphere_id=sphere,
        pk=pk,
        event_pk=event,
        title=f"Session {pk}",
        can_write=can_write,
        can_moderate=can_moderate,
        starts_at=ends_at - EVENT_LENGTH,
        ends_at=ends_at,
    )


def _bootstrapping(access, conversations=None, *, signer=None):
    signer = signer or LengthSigner()
    service = ParleyService(
        repository=access,
        conversations=conversations or NoConversations(),
        signer=signer,
        messages=Messages(None),
        agent_host="parley.example.com",
    )
    return service, signer


def test_bootstrap_grants_a_member_their_own_rooms_in_every_sphere() -> None:
    access = Access(
        [
            _event(12, ends_at=1_786_100_000),
            _session(981, event=12, can_write=False),
            _session(5, event=3, sphere=7),
        ]
    )
    service, signer = _bootstrapping(access)

    result = service.bootstrap(user_id=USER_ID, now=NOW)

    assert result is not None
    assert [room["id"] for room in result.model_dump(mode="json")["rooms"]] == [
        "event:45:12",
        "session:45:981",
        "session:7:5",
    ]
    assert result.model_dump(mode="json", by_alias=True)["rooms"][2] == {
        "id": "session:7:5",
        "kind": "session",
        "sphere": 7,
        "title": "Session 5",
        "canWrite": True,
        "canModerate": False,
        "moderating": False,
        "eventTitle": None,
    }
    assert (result.can_message, result.age_gate) == (False, "unconfirmed")
    assert access.asked == [(NOW, frozenset())]
    claims = signer.signed[-1]
    assert isinstance(claims, ParleyCapabilityClaims)
    assert claims.model_dump(exclude={"jti"}) == {
        "iss": "ludamus",
        "aud": "parley",
        "sub": "123",
        "name": "Ada",
        "avatar": "https://example.com/ada.png",
        "managed": {},
        "events": {
            "45:12": {
                "endsAt": 1_786_100_000,
                "writable": True,
                "chat": True,
                "sessions": {"981": False},
            },
            "7:3": {
                "endsAt": 1_786_000_000,
                "writable": False,
                "chat": False,
                "sessions": {"5": True},
            },
        },
        "readOnlyAfter": 48 * 3600,
        "retainFor": 30 * 24 * 3600,
        "direct": False,
        "iat": 1_786_017_600,
        "exp": 1_786_017_600 + 12 * 3600,
    }
    assert claims.jti
    assert result.capability_token == "t" * 100


def test_a_moderator_s_pass_names_their_spheres_and_events_but_not_the_programme() -> (
    None
):
    access = Access(
        [
            ParleyRoomDTO(
                kind=ParleyRoomKind.ORGANIZERS,
                sphere_id=45,
                title="Bachanalia",
                can_write=True,
                can_moderate=True,
            ),
            _event(1, can_moderate=True),
            *(_session(pk, event=1, can_moderate=True) for pk in range(1, 1001)),
            _session(2000, event=9, sphere=7),
        ],
        seats=[
            (45, SphereRole.MANAGER),
            (7, SphereRole.COMMS),
            (8, SphereRole.MANAGER),
        ],
    )
    service, signer = _bootstrapping(access)

    service.bootstrap(user_id=USER_ID, now=NOW)

    assert access.asked == [(NOW, frozenset({45, 8}))]
    claims = signer.signed[-1]
    assert claims.model_dump()["managed"] == {
        "45": {"organizers": True},
        "8": {"organizers": False},
    }
    assert list(claims.events) == ["45:1", "7:9"]
    assert (claims.events["45:1"].chat, claims.events["45:1"].sessions) == (True, {})


def test_a_pass_too_long_for_a_cookie_drops_the_events_ending_first() -> None:
    rooms = [_event(pk, ends_at=1_786_000_000 + pk) for pk in range(1, 31)]
    rooms.append(_session(500, event=30, ends_at=1_786_000_030))
    moderated_room = _session(99, event=7, sphere=8, can_moderate=True)
    access = Access([*rooms, moderated_room], seats=[(8, SphereRole.MANAGER)])
    service, signer = _bootstrapping(access, signer=LengthSigner(per_event=100))

    result = service.bootstrap(user_id=USER_ID, now=NOW)

    assert result is not None
    assert len(result.capability_token) <= PARLEY_PASS_MAX_LENGTH
    kept = {room.id for room in result.rooms}
    assert kept == {
        *(f"event:45:{pk}" for pk in range(12, 31)),
        "session:45:500",
        "session:8:99",
    }
    assert list(signer.signed[-1].events) == [f"45:{pk}" for pk in range(12, 31)]


def test_a_pass_too_long_for_a_cookie_keeps_the_event_on_now_over_those_far_ahead() -> (
    None
):
    now = int(NOW.timestamp())
    week = 7 * 24 * 3600
    ahead = [_event(pk, ends_at=now + pk * week) for pk in range(1, 21)]
    over = _event(98, ends_at=now - 3600)
    running = _event(99, ends_at=now + 3600)
    access = Access([*ahead, over, running], seats=[(45, SphereRole.MANAGER)])
    service, signer = _bootstrapping(access, signer=LengthSigner(per_event=100))

    result = service.bootstrap(user_id=USER_ID, now=NOW)

    assert result is not None
    assert sorted(signer.signed[-1].events) == sorted(
        ["45:99", "45:98", *(f"45:{pk}" for pk in range(1, 18))]
    )


def test_a_long_event_on_now_outlasts_a_short_one_starting_soon() -> None:
    now = int(NOW.timestamp())
    long_running = _event(1, starts_at=now - 30 * 24 * 3600, ends_at=now + 24 * 3600)
    soon = _event(2, starts_at=now + 3600, ends_at=now + 3 * 3600)
    access = Access([long_running, soon])
    service, signer = _bootstrapping(access, signer=LengthSigner(per_event=1000))

    result = service.bootstrap(user_id=USER_ID, now=NOW)

    assert result is not None
    assert [room.id for room in result.rooms] == ["event:45:1"]
    assert list(signer.signed[-1].events) == ["45:1"]


def test_a_pass_kept_over_its_size_by_events_on_now_says_so(caplog) -> None:
    now = int(NOW.timestamp())
    on_now = [
        _event(pk, starts_at=now - 3600, ends_at=now + 3600) for pk in range(1, 4)
    ]
    service, _ = _bootstrapping(Access(on_now), signer=LengthSigner(per_event=1000))
    caplog.set_level(logging.WARNING, logger="ludamus.mills.parley")

    result = service.bootstrap(user_id=USER_ID, now=NOW)

    assert result is not None
    assert len(result.rooms) == len(on_now)
    assert "fits=False" in caplog.text


def test_bootstrap_lists_party_chats_for_anyone_and_the_rest_once_open() -> None:
    party, group = (
        _conversation(ParleyConversationKind.PARTY),
        _conversation(ParleyConversationKind.GROUP),
    )
    closed, _ = _bootstrapping(Access([]), NoConversations([party, group]))
    opened, _ = _bootstrapping(Access([]), OpenConversations([party, group]))

    shut = closed.bootstrap(user_id=USER_ID, now=NOW)
    open_ = opened.bootstrap(user_id=USER_ID, now=NOW)

    assert shut is not None
    assert open_ is not None
    assert shut.conversations == [party]
    assert open_.conversations == [party, group]


def test_bootstrap_stops_when_there_is_nowhere_to_chat() -> None:
    service, signer = _bootstrapping(Access([]))

    assert service.bootstrap(user_id=USER_ID, now=NOW) is None
    assert not signer.signed


def test_bootstrap_stops_when_repository_denies_access() -> None:
    access = Access(None)
    service, signer = _bootstrapping(access)

    assert service.bootstrap(user_id=USER_ID, now=NOW) is None
    assert access.asked == [(NOW, frozenset())]
    assert not signer.signed


@pytest.mark.parametrize(
    ("conversations", "has_rooms", "expected"),
    (
        (OpenConversations(), False, True),
        (NoConversations(), True, True),
        (NoConversations([_conversation(ParleyConversationKind.PARTY)]), False, True),
        (NoConversations([_conversation(ParleyConversationKind.GROUP)]), False, False),
        (NoConversations(), False, False),
    ),
    ids=["messages", "rooms", "party", "shut-group", "nothing"],
)
def test_the_chat_is_open_to_anyone_with_somewhere_to_chat(
    conversations, has_rooms, expected
) -> None:
    service, _ = _bootstrapping(Access(has_rooms=has_rooms), conversations)

    assert service.is_open_to(user_id=USER_ID, now=NOW) is expected


REPORTER, AUTHOR = 123, 7
# A lookup is signed for the one call that carries it.
LOOKUP_LIFETIME_SECONDS = 60


def _rooms(rooms=((45, 12),)):
    """Give the reporter these rooms, or no chat at all for None."""
    return Access(
        None if rooms is None else [_event(pk, sphere=sphere) for sphere, pk in rooms]
    )


class Members(NoConversations):
    def __init__(self, **states):
        super().__init__()
        self.states = {
            int(key.removeprefix("c")): state for key, state in states.items()
        }

    def read_member(self, *, conversation_id, user_id):
        if (state := self.states.get(conversation_id)) is None:
            return None
        return ParleyMembership(
            kind=ParleyConversationKind.GROUP, state=state, is_admin=False
        )


class Messages:
    """The Worker's answer to a lookup: a message, None, or no answer."""

    def __init__(self, answer):
        self.answer = answer
        self.asked = []

    def read_message(self, token, /):
        self.asked.append(token)
        if self.answer == "down":
            raise ParleyWorkerUnavailableError
        return self.answer

    def moderate(self, token, /):
        self.asked.append(token)
        if token in self.answer:
            raise ParleyWorkerUnavailableError


class RecordingSigner:
    def __init__(self):
        self.signed = []

    def sign(self, claims):
        self.signed.append(claims)
        return f"token-{len(self.signed)}"


def _said_by(author_id):
    return ParleyReportedMessage(
        author_id=str(author_id),
        author_name="Kuba",
        body="You will regret this",
        created_at=datetime(2026, 8, 6, 11, tzinfo=UTC),
        deleted_at=None,
    )


def _reporting(room_id, *, rooms=None, members=None, answer="theirs"):
    rooms = rooms or _rooms()
    messages = Messages(_said_by(AUTHOR) if answer == "theirs" else answer)
    signer = RecordingSigner()
    service = ParleyService(
        repository=rooms,
        conversations=members or Members(),
        signer=signer,
        messages=messages,
        agent_host="parley.example.com",
    )
    created = service.report_message(
        data=ParleyReportData(
            user_id=REPORTER, room_id=room_id, message_id=9, reason="Abuse"
        ),
        now=datetime(2026, 8, 6, 12, tzinfo=UTC),
    )
    return created, rooms.saved, messages.asked, signer.signed


def test_staff_delete_each_reported_message_once_and_resolve_what_its_room_deleted():
    access = Access([])
    access.reported = {
        1: ParleyReportedRef(room_id="event:45:12", message_id=9),
        2: ParleyReportedRef(room_id="conversation:3", message_id=4),
    }
    signer = RecordingSigner()
    messages = Messages(answer={"token-2"})
    service = ParleyService(
        repository=access,
        conversations=Members(),
        signer=signer,
        messages=messages,
        agent_host="parley.example.com",
    )
    now = datetime(2026, 8, 6, 12, tzinfo=UTC)

    result = service.delete_reported(report_ids=[1, 2], now=now)

    assert result == ParleyModerationResult(deleted=1, failed=1)
    assert [(c.aud, c.room, c.message) for c in signer.signed] == [
        ("parley-moderation", "event:45:12", 9),
        ("parley-moderation", "conversation:3", 4),
    ]
    assert access.resolved == [("event:45:12", 9, now)]


def test_a_report_from_a_sphere_room_keeps_what_the_room_said():
    created, saved, asked, signed = _reporting("event:45:12")

    assert created is True
    assert [(r.sphere_id, r.conversation_id, r.message) for r in saved] == [
        (45, None, _said_by(AUTHOR))
    ]
    assert asked == ["token-1"]
    lookup = signed[0]
    assert (lookup.aud, lookup.room, lookup.message) == (
        "parley-message",
        "event:45:12",
        9,
    )
    assert lookup.exp - lookup.iat == LOOKUP_LIFETIME_SECONDS


def test_a_report_from_a_conversation_belongs_to_it_alone():
    created, saved, _, _ = _reporting(
        "conversation:8", members=Members(c8=ParleyMemberState.REQUEST)
    )

    assert created is True
    assert [(r.sphere_id, r.conversation_id) for r in saved] == [(None, 8)]


def test_a_report_stands_without_its_copy_when_the_worker_cannot_say():
    created, saved, _, _ = _reporting("event:45:12", answer="down")

    assert created is True
    assert saved[0].message is None


@pytest.mark.parametrize(
    ("room_id", "rooms", "members"),
    (
        ("event:45:12", _rooms(rooms=None), None),
        ("session:45:3", None, None),
        ("conversation:8", None, Members(c8=ParleyMemberState.LEFT)),
        ("conversation:8", None, Members()),
        ("conversation:x", None, None),
    ),
    ids=["no-chat", "unseen-room", "left", "never-in", "not-an-id"],
)
def test_a_room_out_of_sight_takes_no_report_and_asks_nothing(room_id, rooms, members):
    created, saved, asked, _ = _reporting(room_id, rooms=rooms, members=members)

    assert (created, saved, asked) == (False, [], [])


@pytest.mark.parametrize(
    "answer", (None, _said_by(REPORTER)), ids=("no-such-message", "own")
)
def test_a_message_the_room_lacks_or_ones_own_takes_no_report(answer):
    created, saved, _, _ = _reporting("event:45:12", answer=answer)

    assert (created, saved) == (False, [])


class FakeChatSpheres:
    def __init__(self, *, event_spheres=None, chat_spheres=()):
        self._event_spheres = event_spheres or {}
        self._chat_spheres = list(chat_spheres)

    def read_event_sphere_id(self, event_id):
        return self._event_spheres.get(event_id)

    def list_chat_sphere_ids(self):
        return self._chat_spheres


class FakeOutbox:
    def __init__(self):
        self.scheduled = []

    def schedule(self, *, sphere_ids, subject):
        self.scheduled.append((sphere_ids, subject))


class FakeConversations:
    def __init__(self, conversations=()):
        self._conversations = list(conversations)

    def conversation_ids_of(self, _user_id):
        return self._conversations


class FakeMemberships:
    def __init__(self):
        self.synced = []

    def schedule(self, *, conversation_ids):
        self.synced.extend(conversation_ids)


class FakePartyChats:
    def __init__(self):
        self.synced = []

    def sync_parties_of(self, user_id):
        self.synced.append(user_id)


def _revocations(repository, conversations=()):
    outbox = FakeOutbox()
    service = ParleyRevocationService(
        repository=repository,
        outbox=outbox,
        conversations=FakeConversations(conversations),
        memberships=FakeMemberships(),
        party_chats=FakePartyChats(),
    )
    return service, outbox


def test_a_ban_revokes_the_person_in_the_events_sphere_only_when_it_has_chat():
    service, outbox = _revocations(FakeChatSpheres(event_spheres={7: 45}))

    service.revoke_event_user(event_id=7, user_id=123)
    service.revoke_event_user(event_id=8, user_id=123)

    assert outbox.scheduled == [([45], "123")]


def test_a_disabled_account_is_revoked_in_every_sphere_with_chat():
    service, outbox = _revocations(FakeChatSpheres(chat_spheres=[3, 45]))
    nowhere, quiet = _revocations(FakeChatSpheres())

    service.revoke_user(user_id=123)
    nowhere.revoke_user(user_id=123)

    assert outbox.scheduled == [([3, 45], "123")]
    assert not quiet.scheduled


@pytest.mark.parametrize("change", ("revoke_user", "age_changed"))
def test_a_disabled_account_or_an_age_change_resyncs_its_conversations_and_parties(
    change,
):
    memberships, party_chats = FakeMemberships(), FakePartyChats()
    service = ParleyRevocationService(
        repository=FakeChatSpheres(),
        outbox=FakeOutbox(),
        conversations=FakeConversations([8, 9]),
        memberships=memberships,
        party_chats=party_chats,
    )

    getattr(service, change)(user_id=123)

    assert memberships.synced == [8, 9]
    assert party_chats.synced == [123]


def test_turning_chat_off_revokes_everyone_in_the_sphere():
    service, outbox = _revocations(FakeChatSpheres())

    service.revoke_sphere(sphere_id=45)

    assert outbox.scheduled == [([45], REVOKE_EVERYONE)]


def test_turning_an_event_chat_off_revokes_everyone_in_its_sphere_if_it_has_chat():
    service, outbox = _revocations(FakeChatSpheres(event_spheres={7: 45}))

    service.revoke_event(event_id=7)
    service.revoke_event(event_id=8)

    assert outbox.scheduled == [([45], REVOKE_EVERYONE)]


def test_each_sphere_gets_a_revocation_that_outlives_the_passes_it_voids():
    now = datetime(2026, 8, 6, 12, tzinfo=UTC)
    signed = []

    class Signer:
        @staticmethod
        def sign(claims):
            signed.append(claims)
            return f"token-{claims.sphere}"

    tokens = sign_revocations(
        signer=Signer(), sphere_ids=[3, 45], subject="123", now=now
    )

    assert tokens == ["token-3", "token-45"]
    cutoff = int(now.timestamp())
    for claims in signed:
        assert claims.aud == "parley-revocation"
        assert claims.sub == "123"
        assert claims.revoked_before == cutoff
        assert claims.exp == int((now + PARLEY_TOKEN_LIFETIME).timestamp())
    assert signed[0].jti != signed[1].jti


# What could go wrong: the cutoff runs the wrong way, or on another span than
# the rooms' year, so a copy goes early or outlives its message; or the count
# the sweep reports is not what was cleared.
class CopiedReports:
    def __init__(self, written):
        self.written = written
        self.cleared = []

    def forget_copies_written_before(self, cutoff):
        due = [name for name, at in self.written.items() if at <= cutoff]
        self.cleared.extend(due)
        return len(due)


def test_a_reports_copy_goes_once_its_message_is_a_year_old():
    now = datetime(2027, 8, 6, 12, tzinfo=UTC)
    year = timedelta(days=365)
    reports = CopiedReports(
        {
            "a year ago to the second": now - year,
            "two years ago": now - 2 * year,
            "a minute short of a year": now - year + timedelta(minutes=1),
        }
    )
    service = ParleyReportRetentionService(repository=reports)

    cleared = service.forget_expired_copies(now=now)

    assert cleared == len(reports.cleared)
    assert reports.cleared == ["a year ago to the second", "two years ago"]
