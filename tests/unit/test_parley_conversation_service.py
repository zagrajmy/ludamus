from datetime import UTC, datetime

import pytest

from ludamus.mills.parley_conversations import (
    ParleyConversationService,
    sign_membership,
)
from ludamus.pacts.parley import (
    ParleyConversationDTO,
    ParleyConversationError,
    ParleyConversationKind,
    ParleyMemberSnapshot,
    ParleyMemberState,
    ParleyPersonDTO,
)
from ludamus.specs.parley import PARLEY_GROUP_MAX_MEMBERS
from tests.unit.factories import FakeTransaction

ACTIVE, REQUEST, LEFT = (
    ParleyMemberState.ACTIVE,
    ParleyMemberState.REQUEST,
    ParleyMemberState.LEFT,
)
DIRECT, GROUP = ParleyConversationKind.DIRECT, ParleyConversationKind.GROUP
ME, ADA, BOB, KID, OUT = 1, 2, 3, 4, 5
# A member list older than ten minutes is not to be trusted.
MEMBERSHIP_TTL = 600


class World:
    """People, blocks and conversations as plain data, for the service to change."""

    def __init__(self, *, eligible=(ME, ADA, BOB, *range(100, 200))):
        self.eligible = set(eligible)
        self.blocks: set[tuple[int, int]] = set()
        self.conversations: dict[int, dict] = {}
        self.members: dict[tuple[int, int], tuple[ParleyMemberState, bool]] = {}
        self.lost: set[int] = set()

    def states(self, conversation_id):
        return {
            user: state
            for (conversation, user), (state, _) in self.members.items()
            if conversation == conversation_id
        }

    def is_eligible(self, user_id):
        return user_id in self.eligible

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

    def create_conversation(self, *, kind, title, created_by, pair_key):
        pk = len(self.conversations) + 1
        self.conversations[pk] = {"kind": kind, "pair_key": pair_key, "title": title}
        return pk

    def set_member(self, *, conversation_id, user_id, state, is_admin):
        self.members[conversation_id, user_id] = (state, is_admin)

    def read_member(self, *, conversation_id, user_id):
        if (member := self.members.get((conversation_id, user_id))) is None:
            return None
        return self.conversations[conversation_id]["kind"], member[0], member[1]

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
            state=state,
            can_write=state == ACTIVE,
            is_admin=self.members[conversation_id, user_id][1],
            members=[],
        )

    def snapshot(self, conversation_id):
        return self.conversations[conversation_id]["kind"], [
            ParleyMemberSnapshot(user_id=user, state=state, writable=state == ACTIVE)
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
            user_id=ME, title="  Crew ", member_ids=[ADA, ADA, BOB, KID, ME]
        )

        assert (group.title, group.is_admin) == ("Crew", True)
        assert world.states(1) == {ME: ACTIVE, ADA: ACTIVE}
        assert outbox.sent == [1]

    @pytest.mark.parametrize("title", ("   ", "x" * 81))
    def test_a_title_is_required_and_short(self, service, title):
        _refused(
            "invalid_title",
            service.create_group,
            user_id=ME,
            title=title,
            member_ids=[],
        )

    def test_a_group_has_a_size_limit(self, service):
        people = list(range(100, 100 + PARLEY_GROUP_MAX_MEMBERS))
        _refused(
            "too_many", service.create_group, user_id=ME, title="Big", member_ids=people
        )

    def test_a_minor_cannot_create_one(self, service):
        _refused(
            "forbidden", service.create_group, user_id=KID, title="Kids", member_ids=[]
        )

    def test_its_admin_adds_and_removes_people(self, service, world):
        service.create_group(user_id=ME, title="Crew", member_ids=[ADA])

        service.add_members(user_id=ME, conversation_id=1, member_ids=[ADA, BOB])
        assert world.states(1) == {ME: ACTIVE, ADA: ACTIVE, BOB: ACTIVE}
        service.remove_member(user_id=ME, conversation_id=1, member_id=BOB)
        assert world.states(1)[BOB] == LEFT
        # Someone removed can be added back.
        service.add_members(user_id=ME, conversation_id=1, member_ids=[BOB])
        assert world.states(1)[BOB] == ACTIVE

    def test_adding_stops_at_the_size_limit(self, service):
        service.create_group(user_id=ME, title="Crew", member_ids=[])
        people = list(range(100, 100 + PARLEY_GROUP_MAX_MEMBERS))
        _refused(
            "too_many",
            service.add_members,
            user_id=ME,
            conversation_id=1,
            member_ids=people,
        )

    def test_only_the_admin_of_a_group_shapes_it(self, service):
        service.create_group(user_id=ME, title="Crew", member_ids=[ADA])
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
        service.create_group(user_id=ME, title="Crew", member_ids=[ADA])
        _refused(
            "not_found",
            service.remove_member,
            user_id=ME,
            conversation_id=1,
            member_id=member,
        )


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
