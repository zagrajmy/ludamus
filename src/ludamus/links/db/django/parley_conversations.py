from __future__ import annotations

from django.db.models import Q

from ludamus.links.db.django.models import (
    ParleyBlock,
    ParleyConversation,
    ParleyConversationMember,
    Party,
    PartyMembership,
    User,
)
from ludamus.pacts.parley import (
    CONVERSATION_POLICIES,
    ParleyConversationDTO,
    ParleyConversationKind,
    ParleyConversationPolicy,
    ParleyConversationRepositoryProtocol,
    ParleyMembership,
    ParleyMemberSnapshot,
    ParleyMemberState,
    ParleyPartyCandidate,
    ParleyPersonDTO,
)
from ludamus.pacts.party import PartyMembershipStatus
from ludamus.pacts.user import AgeBand, UserType

_PRESENT = (ParleyMemberState.ACTIVE, ParleyMemberState.REQUEST)
# An unnamed group goes by this many of its people, then a count of the rest.
_NAMES_SHOWN = 3


def _signs_in() -> Q:
    return Q(is_active=True, user_type=UserType.ACTIVE)


def _eligible() -> Q:
    return _signs_in() & Q(age_band=AgeBand.SIXTEEN_PLUS.value)


def _person(user: User) -> ParleyPersonDTO:
    return ParleyPersonDTO(
        id=str(user.pk), name=user.get_full_name(), avatar_url=user.avatar_url
    )


def _blocked(first_id: int, second_id: int) -> bool:
    return ParleyBlock.objects.filter(
        Q(blocker_id=first_id, blocked_id=second_id)
        | Q(blocker_id=second_id, blocked_id=first_id)
    ).exists()


def _blocked_with(user_id: int) -> set[int]:
    pairs = ParleyBlock.objects.filter(
        Q(blocker_id=user_id) | Q(blocked_id=user_id)
    ).values_list("blocker_id", "blocked_id")
    return {pk for pair in pairs for pk in pair} - {user_id}


def _policy(conversation: ParleyConversation) -> ParleyConversationPolicy:
    return CONVERSATION_POLICIES[ParleyConversationKind(conversation.kind)]


def _given_name(conversation: ParleyConversation) -> str:
    # A party's chat goes by the party's name for as long as there is one.
    if conversation.party_id is None:
        return conversation.title
    name = (
        Party.objects.filter(pk=conversation.party_id)
        .values_list("name", flat=True)
        .first()
    )
    return name or ""


def _writable(
    *,
    conversation: ParleyConversation,
    member: ParleyConversationMember,
    others: list[ParleyConversationMember],
) -> bool:
    if member.state != ParleyMemberState.ACTIVE:
        return False
    policy = _policy(conversation)
    if policy.one_to_one:
        # A direct conversation lives while the other person is in it and
        # neither has blocked the other.
        return all(
            other.state != ParleyMemberState.LEFT
            and not _blocked(member.user_id, other.user_id)
            for other in others
        )
    present = [other for other in others if other.state != ParleyMemberState.LEFT]
    # Two in a party's chat are a direct message by another name, a block
    # included.
    if policy.pair_needs_direct and len(present) == 1:
        return not _blocked(member.user_id, present[0].user_id)
    return True


class ParleyConversationRepository(ParleyConversationRepositoryProtocol):
    @staticmethod
    def is_eligible(user_id: int) -> bool:
        return User.objects.filter(_eligible(), pk=user_id).exists()

    @staticmethod
    def read_age_band(user_id: int) -> AgeBand:
        return AgeBand(User.objects.values_list("age_band", flat=True).get(pk=user_id))

    @staticmethod
    def exists(user_id: int) -> bool:
        return User.objects.filter(pk=user_id).exists()

    @staticmethod
    def list_blocked(user_id: int) -> list[ParleyPersonDTO]:
        blocks = (
            ParleyBlock.objects.filter(blocker_id=user_id)
            .select_related("blocked")
            .order_by("blocked__name", "blocked_id")
        )
        return [_person(block.blocked) for block in blocks]

    @staticmethod
    def blocked_between(first_id: int, second_id: int) -> bool:
        return _blocked(first_id, second_id)

    @staticmethod
    def search_people(*, user_id: int, query: str, limit: int) -> list[ParleyPersonDTO]:
        hidden = {user_id} | _blocked_with(user_id)
        people = (
            User.objects.filter(_eligible())
            .filter(Q(name__icontains=query) | Q(username__iexact=query))
            .exclude(pk__in=hidden)
            .order_by("name", "pk")[:limit]
        )
        return [_person(user) for user in people]

    @staticmethod
    def find_direct(pair_key: str) -> int | None:
        return (
            ParleyConversation.objects.filter(pair_key=pair_key)
            .values_list("pk", flat=True)
            .first()
        )

    @staticmethod
    def find_group(member_ids: list[int]) -> int | None:
        # The newest group whose people now are exactly these.
        groups = ParleyConversationMember.objects.filter(
            user_id=member_ids[0],
            state__in=_PRESENT,
            conversation__kind=ParleyConversationKind.GROUP,
        ).values("conversation_id")
        people: dict[int, set[int]] = {}
        for conversation_id, user_id in ParleyConversationMember.objects.filter(
            conversation_id__in=groups, state__in=_PRESENT
        ).values_list("conversation_id", "user_id"):
            people.setdefault(conversation_id, set()).add(user_id)
        wanted = set(member_ids)
        return max(
            (pk for pk, present in people.items() if present == wanted), default=None
        )

    @staticmethod
    def set_title(*, conversation_id: int, title: str) -> None:
        ParleyConversation.objects.filter(pk=conversation_id).update(title=title)

    @staticmethod
    def create_conversation(
        *,
        kind: ParleyConversationKind,
        title: str,
        created_by: int,
        pair_key: str | None,
    ) -> int:
        return ParleyConversation.objects.create(
            kind=kind, title=title, created_by_id=created_by, pair_key=pair_key
        ).pk

    @staticmethod
    def set_member(
        *, conversation_id: int, user_id: int, state: ParleyMemberState, is_admin: bool
    ) -> None:
        ParleyConversationMember.objects.update_or_create(
            conversation_id=conversation_id,
            user_id=user_id,
            defaults={"state": state, "is_admin": is_admin},
        )

    @staticmethod
    def read_member(*, conversation_id: int, user_id: int) -> ParleyMembership | None:
        member = (
            ParleyConversationMember.objects.filter(
                conversation_id=conversation_id, user_id=user_id
            )
            .select_related("conversation")
            .first()
        )
        if member is None:
            return None
        return ParleyMembership(
            kind=ParleyConversationKind(member.conversation.kind),
            state=ParleyMemberState(member.state),
            is_admin=member.is_admin,
        )

    @staticmethod
    def count_active(conversation_id: int) -> int:
        return ParleyConversationMember.objects.filter(
            conversation_id=conversation_id, state__in=_PRESENT
        ).count()

    @staticmethod
    def list_for(user_id: int) -> list[ParleyConversationDTO]:
        conversation_ids = ParleyConversationMember.objects.filter(
            user_id=user_id, state__in=_PRESENT
        ).values_list("conversation_id", flat=True)
        conversations = ParleyConversation.objects.filter(
            pk__in=conversation_ids
        ).order_by("-created_at", "-pk")
        blocked = _blocked_with(user_id)
        return [
            dto
            for conversation in conversations
            if (dto := _conversation_for(conversation, user_id, blocked)) is not None
        ]

    @staticmethod
    def read_for(*, conversation_id: int, user_id: int) -> ParleyConversationDTO | None:
        conversation = ParleyConversation.objects.filter(pk=conversation_id).first()
        if conversation is None:
            return None
        return _conversation_for(conversation, user_id, _blocked_with(user_id))

    @staticmethod
    def snapshot(
        conversation_id: int,
    ) -> tuple[ParleyConversationKind, list[ParleyMemberSnapshot]]:
        conversation = ParleyConversation.objects.get(pk=conversation_id)
        # Everyone, the departed included: a direct conversation dies with
        # either person's leaving.
        everyone = list(conversation.members.select_related("user"))
        signing_in = set(
            User.objects.filter(
                _signs_in(), pk__in=[member.user_id for member in everyone]
            ).values_list("pk", flat=True)
        )
        return ParleyConversationKind(conversation.kind), [
            ParleyMemberSnapshot(
                user_id=member.user_id,
                state=ParleyMemberState(member.state),
                writable=_writable(
                    conversation=conversation,
                    member=member,
                    others=[other for other in everyone if other.pk != member.pk],
                ),
                age_band=AgeBand(member.user.age_band),
                signs_in=member.user_id in signing_in,
            )
            for member in everyone
            if member.state in _PRESENT
        ]

    @staticmethod
    def conversation_ids_of(user_id: int) -> list[int]:
        return list(
            ParleyConversationMember.objects.filter(
                user_id=user_id, state__in=_PRESENT
            ).values_list("conversation_id", flat=True)
        )

    @staticmethod
    def conversations_with(*, first_id: int, second_id: int) -> list[int]:
        shared = ParleyConversationMember.objects.filter(user_id=second_id).values(
            "conversation_id"
        )
        return list(
            ParleyConversationMember.objects.filter(
                user_id=first_id, conversation_id__in=shared
            ).values_list("conversation_id", flat=True)
        )

    @staticmethod
    def block(*, blocker_id: int, blocked_id: int) -> None:
        ParleyBlock.objects.get_or_create(blocker_id=blocker_id, blocked_id=blocked_id)

    @staticmethod
    def unblock(*, blocker_id: int, blocked_id: int) -> None:
        ParleyBlock.objects.filter(
            blocker_id=blocker_id, blocked_id=blocked_id
        ).delete()

    @staticmethod
    def list_party_candidates(party_id: int) -> list[ParleyPartyCandidate]:
        return [
            ParleyPartyCandidate(user_id=user_id, age_band=AgeBand(age_band))
            for user_id, age_band in (
                User.objects.filter(
                    _signs_in(),
                    party_memberships__party_id=party_id,
                    party_memberships__status=PartyMembershipStatus.ACTIVE,
                )
                .order_by("pk")
                .values_list("pk", "age_band")
            )
        ]

    @staticmethod
    def set_party_members(*, party_id: int, user_ids: list[int]) -> int | None:
        conversation = ParleyConversation.objects.filter(party_id=party_id).first()
        party = Party.objects.filter(pk=party_id).first()
        if conversation is None:
            if not user_ids or party is None:
                return None
            conversation = ParleyConversation.objects.create(
                kind=ParleyConversationKind.PARTY, party_id=party_id
            )
        present = set(
            conversation.members.filter(state__in=_PRESENT).values_list(
                "user_id", flat=True
            )
        )
        if present == set(user_ids):
            return None
        conversation.members.filter(user_id__in=present - set(user_ids)).update(
            state=ParleyMemberState.LEFT
        )
        for user_id in set(user_ids) - present:
            ParleyConversationMember.objects.update_or_create(
                conversation=conversation,
                user_id=user_id,
                defaults={"state": ParleyMemberState.ACTIVE, "is_admin": False},
            )
        return conversation.pk

    @staticmethod
    def party_ids_of(user_id: int) -> list[int]:
        member_of = PartyMembership.objects.filter(member_id=user_id).values_list(
            "party_id", flat=True
        )
        chats = ParleyConversationMember.objects.filter(
            user_id=user_id, conversation__party_id__isnull=False
        ).values_list("conversation__party_id", flat=True)
        return sorted({*member_of, *chats})

    @staticmethod
    def list_party_ids() -> list[int]:
        orphaned = ParleyConversation.objects.filter(
            party_id__isnull=False
        ).values_list("party_id", flat=True)
        return sorted({*Party.objects.values_list("pk", flat=True), *orphaned})

    @staticmethod
    def list_party_chat_ids() -> list[int]:
        return list(
            ParleyConversation.objects.filter(party_id__isnull=False)
            .order_by("pk")
            .values_list("pk", flat=True)
        )

    @staticmethod
    def lock_party(party_id: int) -> None:
        list(Party.objects.select_for_update().filter(pk=party_id).values_list("pk"))

    @staticmethod
    def has_conversation(
        *, user_id: int, kinds: frozenset[ParleyConversationKind]
    ) -> bool:
        return ParleyConversationMember.objects.filter(
            user_id=user_id, state__in=_PRESENT, conversation__kind__in=kinds
        ).exists()


def _conversation_for(
    conversation: ParleyConversation, user_id: int, blocked: set[int]
) -> ParleyConversationDTO | None:
    members = list(
        conversation.members.filter(state__in=_PRESENT)
        .select_related("user")
        .order_by("joined_at", "pk")
    )
    own = next((member for member in members if member.user_id == user_id), None)
    if own is None:
        return None
    others = [member for member in members if member.user_id != user_id]
    name = _given_name(conversation)
    return ParleyConversationDTO(
        id=f"conversation:{conversation.pk}",
        kind=ParleyConversationKind(conversation.kind),
        title=name or _default_title(conversation, others, user_id),
        name=name,
        state=ParleyMemberState(own.state),
        can_write=_writable(
            conversation=conversation,
            member=own,
            others=list(conversation.members.exclude(pk=own.pk)),
        ),
        is_admin=own.is_admin,
        members=[_person(member.user) for member in members],
        mentionable=[
            str(member.user_id) for member in others if member.user_id not in blocked
        ],
    )


def _default_title(
    conversation: ParleyConversation,
    others: list[ParleyConversationMember],
    user_id: int,
) -> str:
    if not _policy(conversation).one_to_one:
        names = [member.user.get_full_name() for member in others]
        shown = ", ".join(names[:_NAMES_SHOWN])
        hidden = len(names) - _NAMES_SHOWN
        return f"{shown} +{hidden}" if hidden > 0 else shown
    # The other person, or the last one there was once they have gone.
    other = others[0].user if others else _other_direct_user(conversation, user_id)
    return other.get_full_name() if other is not None else ""


def _other_direct_user(conversation: ParleyConversation, user_id: int) -> User | None:
    member = (
        conversation.members.exclude(user_id=user_id).select_related("user").first()
    )
    return None if member is None else member.user
