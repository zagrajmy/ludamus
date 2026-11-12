from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

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
    ParleyMemberState,
    ParleyReportData,
    ParleyReportedMessage,
    ParleyRoomDTO,
    ParleyRoomKind,
    ParleyWorkerUnavailableError,
)
from ludamus.pacts.user import AgeBand
from ludamus.specs.parley import PARLEY_TOKEN_LIFETIME

NOW = datetime(2026, 8, 6, 12, tzinfo=UTC)
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

    @staticmethod
    def list_blocked(_user_id):
        return []


class OpenConversations(NoConversations):
    @staticmethod
    def is_eligible(_user_id):
        return True


class PartyChats:
    def __init__(self):
        self.synced = []

    def sync_member(self, user_id):
        self.synced.append(user_id)


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


def _access(rooms, managed=()):
    return ParleyAccessDTO(
        user_id=123,
        user_name="Ada",
        user_avatar_url="https://example.com/ada.png",
        rooms=rooms,
        managed_sphere_ids=list(managed),
    )


def _bootstrapping(access, conversations=None, *, has_rooms=False):
    repository = Mock()
    repository.read_access.return_value = access
    repository.has_rooms.return_value = has_rooms
    signer = Mock()
    signer.sign.return_value = "signed-token"
    party_chats = PartyChats()
    service = ParleyService(
        repository=repository,
        conversations=conversations or NoConversations(),
        party_chats=party_chats,
        signer=signer,
        messages=Messages(None),
        agent_host="parley.example.com",
    )
    return service, repository, signer, party_chats


def test_bootstrap_grants_a_member_their_own_rooms_in_every_sphere() -> None:
    service, repository, signer, party_chats = _bootstrapping(
        _access(
            [
                ParleyRoomDTO(
                    id="event:45:12",
                    kind=ParleyRoomKind.EVENT,
                    title="Bachanalia 2026",
                    can_write=True,
                    ends_at=1_786_100_000,
                ),
                ParleyRoomDTO(
                    id="session:45:981",
                    kind=ParleyRoomKind.SESSION,
                    title="Mothership",
                    can_write=False,
                    ends_at=1_786_000_000,
                ),
                ParleyRoomDTO(
                    id="session:7:5",
                    kind=ParleyRoomKind.SESSION,
                    title="Wsiąść do pociągu",
                    can_write=True,
                    ends_at=1_786_200_000,
                ),
            ]
        )
    )

    result = service.bootstrap(user_id=123, now=NOW)

    assert result is not None
    assert result.model_dump(mode="json", by_alias=True) == {
        "user": {
            "id": "123",
            "name": "Ada",
            "avatarUrl": "https://example.com/ada.png",
        },
        "rooms": [
            {
                "id": "event:45:12",
                "kind": "event",
                "title": "Bachanalia 2026",
                "canWrite": True,
                "canModerate": False,
            },
            {
                "id": "session:45:981",
                "kind": "session",
                "title": "Mothership",
                "canWrite": False,
                "canModerate": False,
            },
            {
                "id": "session:7:5",
                "kind": "session",
                "title": "Wsiąść do pociągu",
                "canWrite": True,
                "canModerate": False,
            },
        ],
        "canMessage": False,
        "ageGate": "unconfirmed",
        "conversations": [],
        "blocked": [],
        "capabilityToken": "signed-token",
        "agentHost": "parley.example.com",
    }
    assert repository.read_access.call_args.kwargs["user_id"] == USER_ID
    assert repository.read_access.call_args.kwargs["window"].now == NOW
    assert party_chats.synced == [USER_ID]
    claims = signer.sign.call_args.args[0]
    assert isinstance(claims, ParleyCapabilityClaims)
    assert claims.model_dump(exclude={"jti"}) == {
        "iss": "ludamus",
        "aud": "parley",
        "sub": "123",
        "name": "Ada",
        "avatar": "https://example.com/ada.png",
        "managed": [],
        "sessions": {
            "45:981": {"endsAt": 1_786_000_000, "writable": False},
            "7:5": {"endsAt": 1_786_200_000, "writable": True},
        },
        "events": {"45:12": {"endsAt": 1_786_100_000, "writable": True}},
        "readOnlyAfter": 48 * 3600,
        "retainFor": 30 * 24 * 3600,
        "direct": False,
        "iat": 1_786_017_600,
        "exp": 1_786_017_600 + 12 * 3600,
    }
    assert claims.jti


def test_bootstrap_names_the_spheres_a_manager_moderates_without_their_rooms() -> None:
    service, _, signer, _ = _bootstrapping(
        _access(
            [
                ParleyRoomDTO(
                    id="organizers:45",
                    kind=ParleyRoomKind.ORGANIZERS,
                    title="Bachanalia",
                    can_write=True,
                    can_moderate=True,
                ),
                *(
                    ParleyRoomDTO(
                        id=f"session:45:{pk}",
                        kind=ParleyRoomKind.SESSION,
                        title=f"Session {pk}",
                        can_write=True,
                        can_moderate=True,
                        ends_at=1_786_000_000,
                    )
                    for pk in range(1, 1001)
                ),
            ],
            managed=[45, 7],
        )
    )

    service.bootstrap(user_id=123, now=NOW)

    claims = signer.sign.call_args.args[0]
    assert claims.managed == ["45", "7"]
    assert claims.sessions == {}
    assert claims.events == {}


def test_bootstrap_lists_party_chats_for_anyone_and_the_rest_once_open() -> None:
    party, group = (
        _conversation(ParleyConversationKind.PARTY),
        _conversation(ParleyConversationKind.GROUP),
    )
    closed, _, _, _ = _bootstrapping(_access([]), NoConversations([party, group]))
    opened, _, _, _ = _bootstrapping(_access([]), OpenConversations([party, group]))

    shut = closed.bootstrap(user_id=123, now=NOW)
    open_ = opened.bootstrap(user_id=123, now=NOW)

    assert shut is not None
    assert open_ is not None
    assert shut.conversations == [party]
    assert open_.conversations == [party, group]


def test_bootstrap_stops_when_there_is_nowhere_to_chat() -> None:
    service, _, signer, _ = _bootstrapping(_access([]))

    assert service.bootstrap(user_id=123, now=NOW) is None
    signer.sign.assert_not_called()


def test_bootstrap_stops_when_repository_denies_access() -> None:
    service, repository, signer, party_chats = _bootstrapping(None)

    result = service.bootstrap(user_id=123, now=NOW)

    assert result is None
    repository.read_access.assert_called_once()
    assert repository.read_access.call_args.kwargs["window"].now == NOW
    assert not party_chats.synced
    signer.sign.assert_not_called()


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
    service, _, _, _ = _bootstrapping(None, conversations, has_rooms=has_rooms)

    assert service.is_open_to(user_id=123, now=NOW) is expected


REPORTER, AUTHOR = 123, 7
# A lookup is signed for the one call that carries it.
LOOKUP_LIFETIME_SECONDS = 60


class Rooms:
    """The rooms this reporter sees, and the reports kept."""

    def __init__(self, rooms=("event:45:12",)):
        self.rooms = rooms
        self.saved = []

    def read_access(self, *, user_id, window):
        # No rooms at all: the chat is not open to this person.
        if self.rooms is None:
            return None
        return ParleyAccessDTO(
            user_id=user_id,
            user_name="Ada",
            user_avatar_url="",
            rooms=[
                ParleyRoomDTO(
                    id=room, kind=ParleyRoomKind.EVENT, title="Hall", can_write=True
                )
                for room in self.rooms
            ],
            managed_sphere_ids=[],
        )

    def save_report(self, report):
        self.saved.append(report)


class Members(NoConversations):
    def __init__(self, **states):
        super().__init__()
        self.states = {
            int(key.removeprefix("c")): state for key, state in states.items()
        }

    def read_member(self, *, conversation_id, user_id):
        state = self.states.get(conversation_id)
        return None if state is None else (ParleyConversationKind.GROUP, state, False)


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
    rooms = rooms or Rooms()
    messages = Messages(_said_by(AUTHOR) if answer == "theirs" else answer)
    signer = RecordingSigner()
    service = ParleyService(
        repository=rooms,
        conversations=members or Members(),
        party_chats=PartyChats(),
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
        ("event:45:12", Rooms(rooms=None), None),
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


def _revocations(repository, conversations=()):
    outbox = FakeOutbox()
    service = ParleyRevocationService(
        repository=repository,
        outbox=outbox,
        conversations=FakeConversations(conversations),
        memberships=FakeMemberships(),
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


def test_a_disabled_account_drops_out_of_its_conversations():
    memberships = FakeMemberships()
    service = ParleyRevocationService(
        repository=FakeChatSpheres(),
        outbox=FakeOutbox(),
        conversations=FakeConversations([8, 9]),
        memberships=memberships,
    )

    service.revoke_user(user_id=123)

    assert memberships.synced == [8, 9]


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
