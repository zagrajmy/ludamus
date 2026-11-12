from __future__ import annotations

from django.db.models import Q

from ludamus.links.db.django.models import (
    ParleyBlock,
    ParleyConversation,
    ParleyConversationMember,
    User,
)
from ludamus.pacts.parley import (
    ParleyConversationDTO,
    ParleyConversationKind,
    ParleyConversationRepositoryProtocol,
    ParleyMemberSnapshot,
    ParleyMemberState,
    ParleyPersonDTO,
)
from ludamus.pacts.user import AgeBand, UserType

_PRESENT = (ParleyMemberState.ACTIVE, ParleyMemberState.REQUEST)
# An unnamed group goes by this many of its people, then a count of the rest.
_NAMES_SHOWN = 3


def _eligible() -> Q:
    return Q(
        is_active=True, user_type=UserType.ACTIVE, age_band=AgeBand.SIXTEEN_PLUS.value
    )


def _person(user: User) -> ParleyPersonDTO:
    return ParleyPersonDTO(
        id=str(user.pk), name=user.get_full_name(), avatar_url=user.avatar_url
    )


def _blocked(first_id: int, second_id: int) -> bool:
    return ParleyBlock.objects.filter(
        Q(blocker_id=first_id, blocked_id=second_id)
        | Q(blocker_id=second_id, blocked_id=first_id)
    ).exists()


def _writable(
    *,
    conversation: ParleyConversation,
    member: ParleyConversationMember,
    others: list[ParleyConversationMember],
) -> bool:
    if member.state != ParleyMemberState.ACTIVE:
        return False
    if conversation.kind == ParleyConversationKind.GROUP:
        return True
    # A direct conversation lives while the other person is in it and
    # neither has blocked the other.
    return all(
        other.state != ParleyMemberState.LEFT
        and not _blocked(member.user_id, other.user_id)
        for other in others
    )


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
        blocked = ParleyBlock.objects.filter(
            Q(blocker_id=user_id) | Q(blocked_id=user_id)
        ).values_list("blocker_id", "blocked_id")
        hidden = {user_id} | {pk for pair in blocked for pk in pair}
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
    def read_member(
        *, conversation_id: int, user_id: int
    ) -> tuple[ParleyConversationKind, ParleyMemberState, bool] | None:
        member = (
            ParleyConversationMember.objects.filter(
                conversation_id=conversation_id, user_id=user_id
            )
            .select_related("conversation")
            .first()
        )
        if member is None:
            return None
        return (
            ParleyConversationKind(member.conversation.kind),
            ParleyMemberState(member.state),
            member.is_admin,
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
        return [
            dto
            for conversation in conversations
            if (dto := _conversation_for(conversation, user_id)) is not None
        ]

    @staticmethod
    def read_for(*, conversation_id: int, user_id: int) -> ParleyConversationDTO | None:
        conversation = ParleyConversation.objects.filter(pk=conversation_id).first()
        if conversation is None:
            return None
        return _conversation_for(conversation, user_id)

    @staticmethod
    def snapshot(
        conversation_id: int,
    ) -> tuple[ParleyConversationKind, list[ParleyMemberSnapshot]]:
        conversation = ParleyConversation.objects.get(pk=conversation_id)
        # Everyone, the departed included: a direct conversation dies with
        # either person's leaving. An account no longer eligible, disabled or
        # under 16, is not on the list the Worker gets.
        everyone = list(conversation.members.select_related("user"))
        eligible = set(
            User.objects.filter(
                _eligible(), pk__in=[member.user_id for member in everyone]
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
            )
            for member in everyone
            if member.state in _PRESENT and member.user_id in eligible
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


def _conversation_for(
    conversation: ParleyConversation, user_id: int
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
    return ParleyConversationDTO(
        id=f"conversation:{conversation.pk}",
        kind=ParleyConversationKind(conversation.kind),
        title=conversation.title or _default_title(conversation, others, user_id),
        name=conversation.title,
        state=ParleyMemberState(own.state),
        can_write=_writable(
            conversation=conversation,
            member=own,
            others=list(conversation.members.exclude(pk=own.pk)),
        ),
        is_admin=own.is_admin,
        members=[_person(member.user) for member in members],
    )


def _default_title(
    conversation: ParleyConversation,
    others: list[ParleyConversationMember],
    user_id: int,
) -> str:
    if conversation.kind == ParleyConversationKind.GROUP:
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
