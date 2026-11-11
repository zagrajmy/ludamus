"""Direct and group conversations: who may talk to whom, apart from any sphere.

Anyone 16 or over may write to anyone else who is. A first direct message
arrives as a request, which its recipient reads and then accepts, declines
or answers with a block. A group's creator adds people directly; anyone can
leave. Neither side of a block can reach the other, and neither the search
nor a refusal says that a block is why.
"""

from __future__ import annotations

from secrets import token_urlsafe
from typing import TYPE_CHECKING

from ludamus.pacts.parley import (
    ParleyConversationError,
    ParleyConversationKind,
    ParleyMembershipClaims,
    ParleyMemberState,
)
from ludamus.specs.parley import (
    PARLEY_GROUP_MAX_MEMBERS,
    PARLEY_GROUP_TITLE_MAX_LENGTH,
    PARLEY_PEOPLE_SEARCH_LIMIT,
    PARLEY_PEOPLE_SEARCH_MIN_LENGTH,
)

if TYPE_CHECKING:
    from datetime import datetime

    from ludamus.pacts.parley import (
        ParleyConversationDTO,
        ParleyConversationRepositoryProtocol,
        ParleyMembershipOutboxProtocol,
        ParleyPersonDTO,
        ParleySignerProtocol,
    )
    from ludamus.pacts.services import TransactionProtocol

# A membership snapshot is delivered within minutes or retried afresh, so
# an old one has no business being accepted later.
_MEMBERSHIP_TTL_SECONDS = 600
_PRESENT = (ParleyMemberState.ACTIVE, ParleyMemberState.REQUEST)


def _pk(conversation_id: str) -> int:
    return int(conversation_id.removeprefix("conversation:"))


def _pair_key(first_id: int, second_id: int) -> str:
    low, high = sorted((first_id, second_id))
    return f"{low}:{high}"


class ParleyConversationService:
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        repository: ParleyConversationRepositoryProtocol,
        outbox: ParleyMembershipOutboxProtocol,
    ) -> None:
        self._transaction = transaction
        self._repository = repository
        self._outbox = outbox

    def list_for(self, user_id: int) -> list[ParleyConversationDTO]:
        if not self._repository.is_eligible(user_id):
            return []
        return self._repository.list_for(user_id)

    def search_people(self, *, user_id: int, query: str) -> list[ParleyPersonDTO]:
        query = query.strip()
        if len(
            query
        ) < PARLEY_PEOPLE_SEARCH_MIN_LENGTH or not self._repository.is_eligible(
            user_id
        ):
            return []
        return self._repository.search_people(
            user_id=user_id, query=query, limit=PARLEY_PEOPLE_SEARCH_LIMIT
        )

    def start_direct(self, *, user_id: int, recipient_id: int) -> ParleyConversationDTO:
        self._require_eligible(user_id)
        if user_id == recipient_id or not self._reachable(user_id, recipient_id):
            raise ParleyConversationError("not_found")
        with self._transaction.atomic():
            conversation_id = self._repository.find_direct(
                _pair_key(user_id, recipient_id)
            )
            if conversation_id is None:
                conversation_id = self._repository.create_conversation(
                    kind=ParleyConversationKind.DIRECT,
                    title="",
                    created_by=user_id,
                    pair_key=_pair_key(user_id, recipient_id),
                )
            # Starting it again brings the starter back, and asks again of a
            # recipient who had declined or left; one already in stays as is.
            self._repository.set_member(
                conversation_id=conversation_id,
                user_id=user_id,
                state=self._kept(conversation_id, user_id, ParleyMemberState.ACTIVE),
                is_admin=False,
            )
            self._repository.set_member(
                conversation_id=conversation_id,
                user_id=recipient_id,
                state=self._kept(
                    conversation_id, recipient_id, ParleyMemberState.REQUEST
                ),
                is_admin=False,
            )
            self._outbox.schedule(conversation_ids=[conversation_id])
        return self._read(conversation_id, user_id)

    def accept(self, *, user_id: int, conversation_id: int) -> ParleyConversationDTO:
        self._answer(
            user_id=user_id,
            conversation_id=conversation_id,
            state=ParleyMemberState.ACTIVE,
        )
        return self._read(conversation_id, user_id)

    def decline(self, *, user_id: int, conversation_id: int) -> None:
        self._answer(
            user_id=user_id,
            conversation_id=conversation_id,
            state=ParleyMemberState.LEFT,
        )

    def leave(self, *, user_id: int, conversation_id: int) -> None:
        with self._transaction.atomic():
            member = self._repository.read_member(
                conversation_id=conversation_id, user_id=user_id
            )
            if member is None or member[1] not in _PRESENT:
                raise ParleyConversationError("not_found")
            self._repository.set_member(
                conversation_id=conversation_id,
                user_id=user_id,
                state=ParleyMemberState.LEFT,
                is_admin=False,
            )
            self._outbox.schedule(conversation_ids=[conversation_id])

    def create_group(
        self, *, user_id: int, title: str, member_ids: list[int]
    ) -> ParleyConversationDTO:
        """Talk with these people: the conversation already with them, or a new one.

        One other person is the direct conversation with them; the same people
        as a group already has are that group. A name, if given, is its name.
        """
        self._require_eligible(user_id)
        name = self._valid_name(title)
        if not (added := self._addable(user_id, member_ids)):
            raise ParleyConversationError("no_people")
        if len(added) == 1:
            direct = self.start_direct(user_id=user_id, recipient_id=added[0])
            return self._named(_pk(direct.id), user_id, name)
        if len(added) + 1 > PARLEY_GROUP_MAX_MEMBERS:
            raise ParleyConversationError("too_many")
        with self._transaction.atomic():
            if (existing := self._repository.find_group([user_id, *added])) is not None:
                return self._named(existing, user_id, name)
            conversation_id = self._repository.create_conversation(
                kind=ParleyConversationKind.GROUP,
                title=name,
                created_by=user_id,
                pair_key=None,
            )
            self._repository.set_member(
                conversation_id=conversation_id,
                user_id=user_id,
                state=ParleyMemberState.ACTIVE,
                is_admin=True,
            )
            for member_id in added:
                self._repository.set_member(
                    conversation_id=conversation_id,
                    user_id=member_id,
                    state=ParleyMemberState.ACTIVE,
                    is_admin=False,
                )
            self._outbox.schedule(conversation_ids=[conversation_id])
        return self._read(conversation_id, user_id)

    def add_members(
        self, *, user_id: int, conversation_id: int, member_ids: list[int]
    ) -> ParleyConversationDTO:
        with self._transaction.atomic():
            self._require_admin(user_id, conversation_id)
            added = [
                member_id
                for member_id in self._addable(user_id, member_ids)
                if self._state(conversation_id, member_id) not in _PRESENT
            ]
            if self._repository.count_active(conversation_id) + len(added) > (
                PARLEY_GROUP_MAX_MEMBERS
            ):
                raise ParleyConversationError("too_many")
            for member_id in added:
                self._repository.set_member(
                    conversation_id=conversation_id,
                    user_id=member_id,
                    state=ParleyMemberState.ACTIVE,
                    is_admin=False,
                )
            self._outbox.schedule(conversation_ids=[conversation_id])
        return self._read(conversation_id, user_id)

    def remove_member(
        self, *, user_id: int, conversation_id: int, member_id: int
    ) -> None:
        with self._transaction.atomic():
            self._require_admin(user_id, conversation_id)
            if (
                member_id == user_id
                or self._state(conversation_id, member_id) not in _PRESENT
            ):
                raise ParleyConversationError("not_found")
            self._repository.set_member(
                conversation_id=conversation_id,
                user_id=member_id,
                state=ParleyMemberState.LEFT,
                is_admin=False,
            )
            self._outbox.schedule(conversation_ids=[conversation_id])

    def rename(
        self, *, user_id: int, conversation_id: int, name: str
    ) -> ParleyConversationDTO:
        """Anyone in a conversation names it for everyone; no name clears it."""
        name = self._valid_name(name)
        state = self._state(conversation_id, user_id)
        if state not in _PRESENT:
            raise ParleyConversationError("not_found")
        # A request is answered before it is renamed.
        if state != ParleyMemberState.ACTIVE:
            raise ParleyConversationError("forbidden")
        self._repository.set_title(conversation_id=conversation_id, title=name)
        return self._read(conversation_id, user_id)

    def block(self, *, user_id: int, blocked_id: int) -> None:
        if user_id == blocked_id:
            raise ParleyConversationError("invalid")
        # Anyone at all, so a minor's messages in a sphere's room can be
        # hidden as well.
        if not self._repository.exists(blocked_id):
            raise ParleyConversationError("not_found")
        with self._transaction.atomic():
            self._repository.block(blocker_id=user_id, blocked_id=blocked_id)
            self._outbox.schedule(
                conversation_ids=self._repository.conversations_with(
                    first_id=user_id, second_id=blocked_id
                )
            )

    def unblock(self, *, user_id: int, blocked_id: int) -> None:
        with self._transaction.atomic():
            self._repository.unblock(blocker_id=user_id, blocked_id=blocked_id)
            self._outbox.schedule(
                conversation_ids=self._repository.conversations_with(
                    first_id=user_id, second_id=blocked_id
                )
            )

    def _answer(
        self, *, user_id: int, conversation_id: int, state: ParleyMemberState
    ) -> None:
        with self._transaction.atomic():
            member = self._repository.read_member(
                conversation_id=conversation_id, user_id=user_id
            )
            if member is None or member[1] != ParleyMemberState.REQUEST:
                raise ParleyConversationError("not_found")
            self._repository.set_member(
                conversation_id=conversation_id,
                user_id=user_id,
                state=state,
                is_admin=False,
            )
            self._outbox.schedule(conversation_ids=[conversation_id])

    @staticmethod
    def _valid_name(name: str) -> str:
        name = name.strip()
        if len(name) > PARLEY_GROUP_TITLE_MAX_LENGTH:
            raise ParleyConversationError("invalid_title")
        return name

    def _named(
        self, conversation_id: int, user_id: int, name: str
    ) -> ParleyConversationDTO:
        # An existing conversation keeps its name unless a new one was given.
        if name:
            self._repository.set_title(conversation_id=conversation_id, title=name)
        return self._read(conversation_id, user_id)

    def _require_eligible(self, user_id: int) -> None:
        if not self._repository.is_eligible(user_id):
            raise ParleyConversationError("forbidden")

    def _require_admin(self, user_id: int, conversation_id: int) -> None:
        member = self._repository.read_member(
            conversation_id=conversation_id, user_id=user_id
        )
        if member is None or member[1] not in _PRESENT:
            raise ParleyConversationError("not_found")
        if member[0] != ParleyConversationKind.GROUP or not member[2]:
            raise ParleyConversationError("forbidden")

    def _reachable(self, user_id: int, other_id: int) -> bool:
        return self._repository.is_eligible(
            other_id
        ) and not self._repository.blocked_between(user_id, other_id)

    def _addable(self, user_id: int, member_ids: list[int]) -> list[int]:
        # People who cannot be reached drop out without saying why.
        return [
            member_id
            for member_id in sorted(set(member_ids), key=member_ids.index)
            if member_id != user_id and self._reachable(user_id, member_id)
        ]

    def _state(self, conversation_id: int, user_id: int) -> ParleyMemberState | None:
        member = self._repository.read_member(
            conversation_id=conversation_id, user_id=user_id
        )
        return None if member is None else member[1]

    def _kept(
        self, conversation_id: int, user_id: int, otherwise: ParleyMemberState
    ) -> ParleyMemberState:
        state = self._state(conversation_id, user_id)
        if state is not None and state in _PRESENT:
            return state
        return otherwise

    def _read(self, conversation_id: int, user_id: int) -> ParleyConversationDTO:
        conversation = self._repository.read_for(
            conversation_id=conversation_id, user_id=user_id
        )
        if conversation is None:
            raise ParleyConversationError("not_found")
        return conversation


def sign_membership(
    *,
    signer: ParleySignerProtocol,
    repository: ParleyConversationRepositoryProtocol,
    conversation_id: int,
    now: datetime,
) -> str:
    kind, members = repository.snapshot(conversation_id)
    issued = int(now.timestamp())
    return signer.sign(
        ParleyMembershipClaims(
            iss="ludamus",
            aud="parley-membership",
            conversation=str(conversation_id),
            kind=kind,
            members=[
                {
                    "user": str(member.user_id),
                    "state": member.state,
                    "writable": member.writable,
                }
                for member in members
            ],
            iat=issued,
            exp=issued + _MEMBERSHIP_TTL_SECONDS,
            jti=token_urlsafe(18),
        )
    )
