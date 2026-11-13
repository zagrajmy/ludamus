from datetime import UTC, datetime

import pytest

from ludamus.mills.parley_conversations import (
    ParleyConversationService,
    ParleyPartyChatService,
    chat_members,
    sign_membership,
)
from ludamus.pacts.parley import (
    ParleyChatCandidate,
    ParleyConversationDTO,
    ParleyConversationError,
    ParleyConversationKind,
    ParleyMembership,
    ParleyMemberSnapshot,
    ParleyMemberState,
    ParleyPersonDTO,
)
from ludamus.pacts.user import AgeBand
from ludamus.specs.parley import PARLEY_GROUP_MAX_MEMBERS
from tests.unit.factories import FakeTransaction

ACTIVE, REQUEST, LEFT = (
    ParleyMemberState.ACTIVE,
    ParleyMemberState.REQUEST,
    ParleyMemberState.LEFT,
)
DIRECT, GROUP, PARTY = (
    ParleyConversationKind.DIRECT,
    ParleyConversationKind.GROUP,
    ParleyConversationKind.PARTY,
)
ME, ADA, BOB, KID, OUT = 1, 2, 3, 4, 5
# A member list older than ten minutes is not to be trusted.
MEMBERSHIP_TTL = 600
ONE_YEAR_SECONDS = 365 * 86_400
THREE_YEARS_SECONDS = 3 * ONE_YEAR_SECONDS


class World:
    """People, blocks and conversations as plain data, for the service to change."""

    staff: frozenset[int] = frozenset()

    def __init__(self, *, eligible=(ME, ADA, BOB, *range(100, 200))):
        self.eligible = set(eligible)
        self.blocks: set[tuple[int, int]] = set()
        self.conversations: dict[int, dict] = {}
        self.members: dict[tuple[int, int], tuple[ParleyMemberState, bool]] = {}
        self.lost: set[int] = set()
        self.parties: set[tuple[int, int]] = set()
        self.ages: dict[int, AgeBand] = {}

    def states(self, conversation_id):
        return {
            user: state
            for (conversation, user), (state, _) in self.members.items()
            if conversation == conversation_id
        }

    def is_eligible(self, user_id):
        return user_id in self.eligible

    def exists(self, user_id):
        # Everyone but OUT has an account, the minor KID included.
        return user_id in self.eligible | {KID}

    def blocked_between(self, first_id, second_id):
        return (first_id, second_id) in self.blocks or (
            second_id,
            first_id,
        ) in self.blocks

    def search_people(self, *, user_id, query, limit):
        return [
            ParleyPersonDTO(id=str(pk), name=query, avatar_url="")
            for pk in sorted(self.eligible - {user_id})[:limit]
        ]

    def find_direct(self, pair_key):
        return next(
            (
                pk
                for pk, row in self.conversations.items()
                if row["pair_key"] == pair_key
            ),
            None,
        )

    def find_group(self, member_ids):
        groups = [
            pk
            for pk, row in self.conversations.items()
            if row["kind"] == GROUP
            and {user for user, state in self.states(pk).items() if state != LEFT}
            == set(member_ids)
        ]
        return max(groups, default=None)

    def set_title(self, *, conversation_id, title):
        self.conversations[conversation_id]["title"] = title

    def create_conversation(self, *, kind, title, created_by, pair_key):
        pk = len(self.conversations) + 1
        self.conversations[pk] = {"kind": kind, "pair_key": pair_key, "title": title}
        return pk

    def set_member(self, *, conversation_id, user_id, state, is_admin):
        self.members[conversation_id, user_id] = (state, is_admin)

    def read_member(self, *, conversation_id, user_id):
        if (member := self.members.get((conversation_id, user_id))) is None:
            return None
        return ParleyMembership(
            kind=self.conversations[conversation_id]["kind"],
            state=member[0],
            is_admin=member[1],
        )

    def count_active(self, conversation_id):
        return sum(
            state in {ACTIVE, REQUEST}
            for state in self.states(conversation_id).values()
        )

    def list_for(self, user_id):
        return [
            dto
            for pk in self.conversations
            if (dto := self.read_for(conversation_id=pk, user_id=user_id)) is not None
        ]

    def read_for(self, *, conversation_id, user_id):
        state = self.states(conversation_id).get(user_id)
        if conversation_id in self.lost or state not in {ACTIVE, REQUEST}:
            return None
        return ParleyConversationDTO(
            id=f"conversation:{conversation_id}",
            kind=self.conversations[conversation_id]["kind"],
            title=self.conversations[conversation_id]["title"],
            name=self.conversations[conversation_id]["title"],
            state=state,
            can_write=state == ACTIVE,
            is_admin=self.members[conversation_id, user_id][1],
            members=[],
        )

    def snapshot(self, conversation_id):
        return self.conversations[conversation_id]["kind"], [
            ParleyMemberSnapshot(
                user_id=user,
                state=state,
                writable=state == ACTIVE,
                age_band=self.read_age_band(user),
                signs_in=user != OUT,
                is_staff=user in self.staff,
            )
            for user, state in self.states(conversation_id).items()
            if state != LEFT
        ]

    def conversations_with(self, *, first_id, second_id):
        return [
            pk
            for pk in self.conversations
            if {first_id, second_id} <= set(self.states(pk))
        ]

    def block(self, *, blocker_id, blocked_id):
        self.blocks.add((blocker_id, blocked_id))

    def unblock(self, *, blocker_id, blocked_id):
        self.blocks.discard((blocker_id, blocked_id))

    def read_age_band(self, user_id):
        if user_id in self.ages:
            return self.ages[user_id]
        if user_id == KID:
            return AgeBand.THIRTEEN_TO_FIFTEEN
        return AgeBand.SIXTEEN_PLUS if user_id in self.eligible else AgeBand.UNKNOWN

    def list_party_candidates(self, party_id):
        return [
            ParleyChatCandidate(user_id=user, age_band=self.read_age_band(user))
            for party, user in sorted(self.parties)
            if party == party_id
        ]

    def set_party_members(self, *, party_id, user_ids):
        chat = next(
            (
                pk
                for pk, row in self.conversations.items()
                if row.get("party") == party_id
            ),
            None,
        )
        if chat is None:
            if not user_ids:
                return None
            chat = len(self.conversations) + 1
            self.conversations[chat] = {
                "kind": PARTY,
                "pair_key": None,
                "party": party_id,
                "title": "Drużyna",
            }
        present = {user for user, state in self.states(chat).items() if state != LEFT}
        if present == set(user_ids):
            return None
        for user in present:
            self.members[chat, user] = (LEFT, False)
        for user in user_ids:
            self.members[chat, user] = (ACTIVE, False)
        return chat

    def party_ids_of(self, user_id):
        in_chat = {
            row["party"]
            for pk, row in self.conversations.items()
            if "party" in row and user_id in self.states(pk)
        }
        return sorted(
            {party for party, user in self.parties if user == user_id} | in_chat
        )

    def list_party_ids(self):
        kept = {row["party"] for row in self.conversations.values() if "party" in row}
        return sorted({party for party, _ in self.parties} | kept)

    def list_party_chat_ids(self):
        return sorted(pk for pk, row in self.conversations.items() if "party" in row)

    def lock_party(self, party_id):
        pass


class Outbox:
    def __init__(self):
        self.sent: list[int] = []

    def schedule(self, *, conversation_ids):
        self.sent.extend(conversation_ids)


@pytest.fixture(name="world")
def _world():
    return World()


@pytest.fixture(name="outbox")
def _outbox():
    return Outbox()


@pytest.fixture(name="service")
def _service(world, outbox):
    return ParleyConversationService(
        transaction=FakeTransaction(), repository=world, outbox=outbox
    )


def _refused(code, call, *args, **kwargs):
    with pytest.raises(ParleyConversationError) as raised:
        call(*args, **kwargs)
    assert raised.value.code == code


class TestPeopleAndLists:
    def test_search_needs_two_letters_and_an_eligible_searcher(self, service, world):
        assert service.search_people(user_id=ME, query=" a ") == []
        assert [person.id for person in service.search_people(user_id=ME, query="ad")][
            :2
        ] == ["2", "3"]
        world.eligible.discard(ME)
        assert service.search_people(user_id=ME, query="ada") == []

    def test_the_list_is_empty_for_someone_out_of_reach(self, service, world):
        service.start_direct(user_id=ME, recipient_id=ADA)
        assert len(service.list_for(ME)) == 1
        world.eligible.discard(ME)
        assert service.list_for(ME) == []


class TestDirect:
    def test_a_first_message_is_a_request_the_recipient_answers(
        self, service, world, outbox
    ):
        started = service.start_direct(user_id=ME, recipient_id=ADA)

        assert started.state == ACTIVE
        assert world.states(1) == {ME: ACTIVE, ADA: REQUEST}
        assert service.accept(user_id=ADA, conversation_id=1).state == ACTIVE
        assert world.states(1) == {ME: ACTIVE, ADA: ACTIVE}
        # The answer is final: there is no request left to answer.
        _refused("not_found", service.accept, user_id=ADA, conversation_id=1)
        _refused("not_found", service.decline, user_id=ME, conversation_id=1)
        assert outbox.sent == [1, 1]

    def test_starting_again_reuses_it_and_asks_again(self, service, world):
        service.start_direct(user_id=ME, recipient_id=ADA)
        service.decline(user_id=ADA, conversation_id=1)
        service.leave(user_id=ME, conversation_id=1)

        service.start_direct(user_id=ME, recipient_id=ADA)

        assert list(world.conversations) == [1]
        assert world.states(1) == {ME: ACTIVE, ADA: REQUEST}

    def test_someone_already_in_stays_as_they_are(self, service, world):
        service.start_direct(user_id=ME, recipient_id=ADA)
        service.accept(user_id=ADA, conversation_id=1)

        service.start_direct(user_id=ADA, recipient_id=ME)

        assert world.states(1) == {ME: ACTIVE, ADA: ACTIVE}

    @pytest.mark.parametrize("recipient", (ME, KID), ids=("oneself", "out of reach"))
    def test_nobody_out_of_reach_can_be_written_to(self, service, recipient):
        _refused("not_found", service.start_direct, user_id=ME, recipient_id=recipient)

    def test_a_block_either_way_reads_as_nobody_there(self, service, world):
        world.blocks.add((ADA, ME))
        _refused("not_found", service.start_direct, user_id=ME, recipient_id=ADA)

    def test_a_minor_cannot_start_one(self, service):
        _refused("forbidden", service.start_direct, user_id=KID, recipient_id=ADA)

    def test_a_conversation_lost_on_the_way_reads_as_not_found(self, service, world):
        world.lost.add(1)
        _refused("not_found", service.start_direct, user_id=ME, recipient_id=ADA)

    def test_only_a_member_can_leave(self, service, world):
        service.start_direct(user_id=ME, recipient_id=ADA)
        _refused("not_found", service.leave, user_id=BOB, conversation_id=1)
        service.leave(user_id=ME, conversation_id=1)
        _refused("not_found", service.leave, user_id=ME, conversation_id=1)
        assert world.states(1) == {ME: LEFT, ADA: REQUEST}


class TestGroups:
    def test_the_creator_adds_reachable_people_once_each(self, service, world, outbox):
        world.blocks.add((BOB, ME))

        group = service.create_group(
            user_id=ME, title="  Crew ", member_ids=[ADA, ADA, BOB, KID, ME, 100]
        )

        assert (group.title, group.is_admin) == ("Crew", True)
        assert world.states(1) == {ME: ACTIVE, ADA: ACTIVE, 100: ACTIVE}
        assert outbox.sent == [1]

    def test_a_name_is_optional_but_short(self, service):
        unnamed = service.create_group(user_id=ME, title="   ", member_ids=[ADA, BOB])

        assert not unnamed.name
        _refused(
            "invalid_title",
            service.create_group,
            user_id=ME,
            title="x" * 81,
            member_ids=[ADA, BOB],
        )

    @pytest.mark.parametrize(
        "people", ([], [KID, OUT, ME]), ids=("none", "unreachable")
    )
    def test_a_conversation_needs_someone_to_talk_to(self, service, people):
        _refused(
            "no_people", service.create_group, user_id=ME, title="", member_ids=people
        )

    def test_the_same_people_get_the_conversation_they_already_have(
        self, service, world
    ):
        first = service.create_group(user_id=ME, title="Crew", member_ids=[ADA, BOB])

        again = service.create_group(user_id=ME, title="", member_ids=[BOB, ADA, BOB])
        renamed = service.create_group(user_id=ME, title="Party", member_ids=[ADA, BOB])

        assert again.id == renamed.id == first.id
        assert (again.title, renamed.title) == ("Crew", "Party")
        assert len(world.conversations) == 1

    def test_other_people_or_fewer_of_them_get_a_conversation_of_their_own(
        self, service, world
    ):
        service.create_group(user_id=ME, title="", member_ids=[ADA, BOB])
        service.create_group(user_id=ME, title="", member_ids=[ADA, BOB, 100])
        world.members[1, BOB] = (LEFT, False)

        ours = service.create_group(user_id=ME, title="", member_ids=[ADA, BOB])

        assert ours.id == "conversation:3"

    def test_one_other_person_is_the_direct_conversation_with_them(
        self, service, world
    ):
        direct = service.start_direct(user_id=ME, recipient_id=ADA)

        named = service.create_group(user_id=ME, title="Us two", member_ids=[ADA])

        assert (named.id, named.kind, named.title) == (direct.id, DIRECT, "Us two")
        assert len(world.conversations) == 1

    def test_a_group_has_a_size_limit(self, service):
        people = list(range(100, 100 + PARLEY_GROUP_MAX_MEMBERS))
        _refused(
            "too_many", service.create_group, user_id=ME, title="Big", member_ids=people
        )

    def test_a_minor_cannot_create_one(self, service):
        _refused(
            "forbidden",
            service.create_group,
            user_id=KID,
            title="Kids",
            member_ids=[ADA, BOB],
        )

    def test_its_admin_adds_and_removes_people(self, service, world):
        service.create_group(user_id=ME, title="Crew", member_ids=[ADA, 100])

        service.add_members(user_id=ME, conversation_id=1, member_ids=[ADA, BOB])
        assert world.states(1) == {ME: ACTIVE, ADA: ACTIVE, 100: ACTIVE, BOB: ACTIVE}
        service.remove_member(user_id=ME, conversation_id=1, member_id=BOB)
        assert world.states(1)[BOB] == LEFT
        # Someone removed can be added back.
        service.add_members(user_id=ME, conversation_id=1, member_ids=[BOB])
        assert world.states(1)[BOB] == ACTIVE

    def test_adding_stops_at_the_size_limit(self, service):
        service.create_group(user_id=ME, title="Crew", member_ids=[ADA, BOB])
        people = list(range(100, 100 + PARLEY_GROUP_MAX_MEMBERS))
        _refused(
            "too_many",
            service.add_members,
            user_id=ME,
            conversation_id=1,
            member_ids=people,
        )

    def test_only_the_admin_of_a_group_shapes_it(self, service):
        service.create_group(user_id=ME, title="Crew", member_ids=[ADA, 100])
        service.start_direct(user_id=ME, recipient_id=BOB)

        _refused(
            "forbidden",
            service.add_members,
            user_id=ADA,
            conversation_id=1,
            member_ids=[BOB],
        )
        _refused(
            "forbidden",
            service.remove_member,
            user_id=ADA,
            conversation_id=1,
            member_id=ME,
        )
        _refused(
            "forbidden",
            service.add_members,
            user_id=ME,
            conversation_id=2,
            member_ids=[ADA],
        )
        _refused(
            "not_found",
            service.add_members,
            user_id=BOB,
            conversation_id=1,
            member_ids=[],
        )

    @pytest.mark.parametrize("member", (ME, BOB), ids=("oneself", "not in it"))
    def test_removing_needs_someone_else_who_is_in_it(self, service, member):
        service.create_group(user_id=ME, title="Crew", member_ids=[ADA, 100])
        _refused(
            "not_found",
            service.remove_member,
            user_id=ME,
            conversation_id=1,
            member_id=member,
        )


class TestNames:
    def test_anyone_in_it_names_it_for_everyone_and_no_name_clears_it(
        self, service, world
    ):
        service.create_group(user_id=ME, title="", member_ids=[ADA, BOB])

        named = service.rename(user_id=ADA, conversation_id=1, name="  Crew  ")
        assert named.name == "Crew"
        assert service.list_for(BOB)[0].name == "Crew"
        assert not service.rename(user_id=ME, conversation_id=1, name="").name

    def test_a_request_is_answered_before_it_is_renamed(self, service):
        service.start_direct(user_id=ME, recipient_id=ADA)

        _refused("forbidden", service.rename, user_id=ADA, conversation_id=1, name="X")
        assert service.rename(user_id=ME, conversation_id=1, name="X").name == "X"

    def test_only_someone_in_it_renames_it(self, service, world):
        service.create_group(user_id=ME, title="", member_ids=[ADA, BOB])
        service.leave(user_id=ADA, conversation_id=1)

        for outsider in (ADA, 100):
            _refused(
                "not_found",
                service.rename,
                user_id=outsider,
                conversation_id=1,
                name="Ours",
            )
        assert not world.conversations[1]["title"]

    def test_a_name_is_short(self, service):
        service.create_group(user_id=ME, title="", member_ids=[ADA, BOB])
        _refused(
            "invalid_title",
            service.rename,
            user_id=ME,
            conversation_id=1,
            name="x" * 81,
        )


def _candidates(*members):
    return [
        ParleyChatCandidate(user_id=user_id, age_band=age_band)
        for user_id, age_band in enumerate(members, start=1)
    ]


ADULT, TEEN, UNSURE = (
    AgeBand.SIXTEEN_PLUS,
    AgeBand.THIRTEEN_TO_FIFTEEN,
    AgeBand.UNKNOWN,
)


@pytest.mark.parametrize(
    ("members", "talking"),
    (
        ((ADULT, ADULT), [1, 2]),
        ((ADULT, TEEN), []),
        ((ADULT, UNSURE), []),
        ((TEEN, TEEN), []),
        ((ADULT, ADULT, TEEN), [1, 2, 3]),
        ((TEEN, UNSURE, TEEN), [1, 2, 3]),
        ((ADULT,), []),
        ((), []),
    ),
    ids=[
        "two-adults",
        "adult-and-teen",
        "adult-and-unconfirmed-age",
        "two-teens",
        "three-with-a-teen",
        "three-under-16",
        "alone",
        "nobody",
    ],
)
def test_a_party_chat_takes_in_any_age_but_not_a_pair_short_of_direct_messages(
    members, talking
):
    assert chat_members(_candidates(*members)) == talking


class TestPartyChats:
    """A party's chat follows its members, closing while it would be a DM."""

    @pytest.fixture(name="chats")
    @staticmethod
    def _chats(world, outbox):
        return ParleyPartyChatService(
            transaction=FakeTransaction(), repository=world, outbox=outbox
        )

    def test_opens_for_every_age_once_a_pair_grows(self, chats, world, outbox):
        world.parties = {(7, ME), (7, KID)}
        chats.sync_party(7)
        assert (world.conversations, outbox.sent) == ({}, [])

        world.parties.add((7, ADA))
        chats.sync_party(7)
        chats.sync_party(7)

        assert world.states(1) == {ME: ACTIVE, KID: ACTIVE, ADA: ACTIVE}
        assert outbox.sent == [1]

    def test_closes_for_both_when_it_shrinks_to_a_pair_with_a_teen_and_comes_back(
        self, chats, world, outbox
    ):
        world.parties = {(7, ME), (7, KID), (7, ADA)}
        chats.sync_party(7)
        world.parties.discard((7, ADA))

        chats.sync_party(7)
        assert world.states(1) == {ME: LEFT, KID: LEFT, ADA: LEFT}
        assert world.list_for(KID) == []

        world.parties.add((7, BOB))
        chats.sync_party(7)
        assert world.states(1) == {ME: ACTIVE, KID: ACTIVE, ADA: LEFT, BOB: ACTIVE}
        assert outbox.sent == [1, 1, 1]

    def test_lets_go_of_everyone_once_the_party_is_gone(self, chats, world, outbox):
        world.parties = {(7, ME), (7, ADA)}
        chats.sync_party(7)
        world.parties.clear()

        chats.sync_party(7)

        assert world.states(1) == {ME: LEFT, ADA: LEFT}
        assert outbox.sent == [1, 1]

    def test_follows_someone_into_and_out_of_their_parties_chats(
        self, chats, world, outbox
    ):
        world.parties = {(7, ME), (7, ADA), (8, KID), (8, ADA)}

        chats.sync_parties_of(KID)
        chats.sync_parties_of(ME)
        chats.sync_parties_of(ME)

        assert world.states(1) == {ME: ACTIVE, ADA: ACTIVE}
        assert outbox.sent == [1]
        world.ages = {KID: ADULT}
        chats.sync_parties_of(KID)
        assert world.states(2) == {KID: ACTIVE, ADA: ACTIVE}
        world.ages = {KID: TEEN}
        chats.sync_parties_of(KID)
        assert world.states(2) == {KID: LEFT, ADA: LEFT}

    def test_opens_the_chats_of_every_party_made_before_them(
        self, chats, world, outbox
    ):
        world.parties = {(7, ME), (7, ADA), (8, KID)}

        assert [chats.open_existing_chats(), chats.open_existing_chats()] == [2, 2]
        assert world.states(1) == {ME: ACTIVE, ADA: ACTIVE}
        # Each run sends every list again, in case the last delivery failed.
        assert outbox.sent == [1, 1]

    def test_lets_everyone_go_once_the_party_is_gone(self, chats, world, outbox):
        world.parties = {(7, ME), (7, ADA), (7, BOB)}
        chats.sync_party(7)
        world.parties = set()

        assert chats.open_existing_chats() == 1
        assert world.states(1) == {ME: LEFT, ADA: LEFT, BOB: LEFT}
        assert outbox.sent == [1, 1]

    def test_is_listed_for_someone_direct_messages_are_shut_to(self, chats, world):
        world.parties = {(7, ME), (7, ADA)}
        chats.sync_party(7)
        service = ParleyConversationService(
            transaction=FakeTransaction(), repository=world, outbox=Outbox()
        )
        world.eligible.discard(ME)

        assert [conversation.kind for conversation in service.list_for(ME)] == [PARTY]

    def test_is_left_and_renamed_only_through_the_party(self, chats, world, service):
        world.parties = {(7, ME), (7, ADA)}
        chats.sync_party(7)

        _refused("forbidden", service.leave, user_id=ME, conversation_id=1)
        _refused("forbidden", service.rename, user_id=ME, conversation_id=1, name="X")
        assert world.states(1) == {ME: ACTIVE, ADA: ACTIVE}


class TestBlocks:
    def test_a_block_updates_every_shared_conversation(self, service, world, outbox):
        service.start_direct(user_id=ME, recipient_id=ADA)
        service.create_group(user_id=ME, title="Crew", member_ids=[ADA, BOB])
        outbox.sent.clear()

        service.block(user_id=ME, blocked_id=ADA)
        assert (ME, ADA) in world.blocks
        assert outbox.sent == [1, 2]
        service.unblock(user_id=ME, blocked_id=ADA)
        assert world.blocks == set()
        assert outbox.sent == [1, 2, 1, 2]

    @pytest.mark.parametrize(("blocked", "code"), ((ME, "invalid"), (OUT, "not_found")))
    def test_a_block_needs_someone_else_who_is_there(self, service, blocked, code):
        _refused(code, service.block, user_id=ME, blocked_id=blocked)

    def test_anyone_with_an_account_can_be_blocked_a_minor_too(self, service, world):
        service.block(user_id=ME, blocked_id=KID)
        assert (ME, KID) in world.blocks


def test_the_member_list_is_signed_as_its_own_kind_of_token(world):
    world.conversations[1] = {"kind": DIRECT, "pair_key": "1:2", "title": ""}
    world.members[1, ME] = (ACTIVE, False)
    world.members[1, ADA] = (REQUEST, False)
    world.members[1, BOB] = (LEFT, False)
    signed = []

    class Signer:
        @staticmethod
        def sign(claims):
            signed.append(claims)
            return "token"

    now = datetime(2026, 11, 10, 12, tzinfo=UTC)

    assert (
        sign_membership(signer=Signer(), repository=world, conversation_id=1, now=now)
        == "token"
    )
    claims = signed[0]
    assert len(signed) == 1
    assert (claims.aud, claims.conversation, claims.kind) == (
        "parley-membership",
        "1",
        DIRECT,
    )
    assert claims.members == [
        {"user": "1", "state": ACTIVE, "writable": True},
        {"user": "2", "state": REQUEST, "writable": False},
    ]
    assert claims.exp - claims.iat == MEMBERSHIP_TTL
    assert claims.needs_direct is True
    assert claims.retain_for == ONE_YEAR_SECONDS


@pytest.mark.parametrize(
    ("members", "listed"),
    (((ME, ADA), [ME, ADA]), ((ME, KID), []), ((ME, KID, ADA), [ME, KID, ADA])),
    ids=["two-adults", "adult-and-teen", "three-with-a-teen"],
)
def test_a_party_chat_s_member_list_keeps_its_pair_rule_whoever_sends_it(
    world, members, listed
):
    # The Worker hears the rule from every list, not only from a party sync:
    # a block or an account closing resends the list too.
    world.conversations[1] = {"kind": PARTY, "pair_key": None, "party": 7, "title": ""}
    for member in members:
        world.members[1, member] = (ACTIVE, False)
    signed = []

    class Signer:
        @staticmethod
        def sign(claims):
            signed.append(claims)
            return "token"

    sign_membership(
        signer=Signer(),
        repository=world,
        conversation_id=1,
        now=datetime(2026, 11, 10, 12, tzinfo=UTC),
    )

    assert [int(member["user"]) for member in signed[0].members] == listed
    assert signed[0].needs_direct is False


@pytest.mark.parametrize(
    ("kind", "listed", "kept"),
    (
        (GROUP, [ME, ADA], ONE_YEAR_SECONDS),
        (PARTY, [ME, ADA, KID], ONE_YEAR_SECONDS),
        (ParleyConversationKind.STAFF, [ME, KID], THREE_YEARS_SECONDS),
    ),
    ids=["group", "party", "staff case thread"],
)
def test_a_member_list_leaves_out_who_cannot_sign_in_or_is_too_young_for_the_kind(
    world, kind, listed, kept
):
    # A staff case's thread takes only staff, kept as long as the case's records.
    world.staff = frozenset({ME, KID, OUT})
    world.conversations[1] = {"kind": kind, "pair_key": None, "party": 7, "title": ""}
    for member in (ME, ADA, KID, OUT):
        world.members[1, member] = (ACTIVE, False)
    signed = []

    class Signer:
        @staticmethod
        def sign(claims):
            signed.append(claims)
            return "token"

    sign_membership(
        signer=Signer(),
        repository=world,
        conversation_id=1,
        now=datetime(2026, 11, 10, 12, tzinfo=UTC),
    )

    assert [int(member["user"]) for member in signed[0].members] == listed
    assert signed[0].retain_for == kept
