"""The chats a party, an encounter or a board owns, one repository per kind."""

from __future__ import annotations

from django.db.models import Q

from ludamus.links.db.django.models import (
    Board,
    BoardVisit,
    Encounter,
    EncounterRSVP,
    ParleyConversation,
    ParleyConversationMember,
    Party,
    PartyMembership,
    User,
)
from ludamus.links.db.django.parley_conversations import set_members, signs_in
from ludamus.pacts.parley import (
    ParleyChatCandidate,
    ParleyConversationKind,
    ParleyMemberState,
    ParleyOwnedChatRepositoryProtocol,
)
from ludamus.pacts.party import PartyMembershipStatus
from ludamus.pacts.user import AgeBand

_PRESENT = (ParleyMemberState.ACTIVE, ParleyMemberState.REQUEST)


def _candidates(users: Q) -> list[ParleyChatCandidate]:
    return [
        ParleyChatCandidate(user_id=user_id, age_band=AgeBand(age_band))
        for user_id, age_band in (
            User.objects.filter(signs_in(), users)
            .order_by("pk")
            .values_list("pk", "age_band")
        )
    ]


def _replace_members(
    conversation: ParleyConversation | None, user_ids: list[int]
) -> int | None:
    """Make `user_ids` a chat's members.

    Returns:
        The chat's id when who is in it changed, else None.
    """
    if conversation is None:
        return None
    present = set(
        conversation.members.filter(state__in=_PRESENT).values_list(
            "user_id", flat=True
        )
    )
    if present == set(user_ids):
        return None
    set_members(conversation_id=conversation.pk, present=present, wanted=set(user_ids))
    return conversation.pk


def _chat_ids(chats: Q) -> list[int]:
    return list(
        ParleyConversation.objects.filter(chats)
        .order_by("pk")
        .values_list("pk", flat=True)
    )


class PartyChatRepository(ParleyOwnedChatRepositoryProtocol):
    kind = ParleyConversationKind.PARTY

    @staticmethod
    def lock(owner_id: int) -> None:
        list(Party.objects.select_for_update().filter(pk=owner_id).values_list("pk"))

    @staticmethod
    def list_candidates(owner_id: int) -> list[ParleyChatCandidate]:
        return _candidates(
            Q(
                party_memberships__party_id=owner_id,
                party_memberships__status=PartyMembershipStatus.ACTIVE,
            )
        )

    @staticmethod
    def set_members(*, owner_id: int, user_ids: list[int]) -> int | None:
        chat = ParleyConversation.objects.filter(party_id=owner_id).first()
        if chat is None and user_ids and Party.objects.filter(pk=owner_id).exists():
            chat = ParleyConversation.objects.create(
                kind=ParleyConversationKind.PARTY, party_id=owner_id
            )
        return _replace_members(chat, user_ids)

    @staticmethod
    def owner_ids_of(user_id: int) -> list[int]:
        member_of = PartyMembership.objects.filter(member_id=user_id).values_list(
            "party_id", flat=True
        )
        chats = ParleyConversationMember.objects.filter(
            user_id=user_id, conversation__party_id__isnull=False
        ).values_list("conversation__party_id", flat=True)
        return sorted({*member_of, *chats})

    @staticmethod
    def list_owner_ids() -> list[int]:
        orphaned = ParleyConversation.objects.filter(
            party_id__isnull=False
        ).values_list("party_id", flat=True)
        return sorted({*Party.objects.values_list("pk", flat=True), *orphaned})

    @staticmethod
    def list_chat_ids() -> list[int]:
        return _chat_ids(Q(party_id__isnull=False))

    @staticmethod
    def chat_id(owner_id: int) -> int | None:
        return (
            ParleyConversation.objects.filter(party_id=owner_id)
            .values_list("pk", flat=True)
            .first()
        )


class EncounterChatRepository(ParleyOwnedChatRepositoryProtocol):
    kind = ParleyConversationKind.ENCOUNTER

    @staticmethod
    def lock(owner_id: int) -> None:
        list(
            Encounter.objects.select_for_update().filter(pk=owner_id).values_list("pk")
        )

    @staticmethod
    def list_candidates(owner_id: int) -> list[ParleyChatCandidate]:
        # Nobody while the encounter's sphere has chat off.
        creator_id = (
            Encounter.objects.filter(pk=owner_id, sphere__parley_enabled=True)
            .values_list("creator_id", flat=True)
            .first()
        )
        if creator_id is None:
            return []
        signed_up = EncounterRSVP.objects.filter(encounter_id=owner_id).values(
            "user_id"
        )
        return _candidates(Q(pk=creator_id) | Q(pk__in=signed_up))

    @staticmethod
    def set_members(*, owner_id: int, user_ids: list[int]) -> int | None:
        chat = ParleyConversation.objects.filter(encounter_id=owner_id).first()
        if chat is None and user_ids and Encounter.objects.filter(pk=owner_id).exists():
            chat = ParleyConversation.objects.create(
                kind=ParleyConversationKind.ENCOUNTER, encounter_id=owner_id
            )
        return _replace_members(chat, user_ids)

    @staticmethod
    def owner_ids_of(user_id: int) -> list[int]:
        made = Encounter.objects.filter(creator_id=user_id).values_list("pk", flat=True)
        signed_up = EncounterRSVP.objects.filter(user_id=user_id).values_list(
            "encounter_id", flat=True
        )
        chats = ParleyConversationMember.objects.filter(
            user_id=user_id, conversation__encounter_id__isnull=False
        ).values_list("conversation__encounter_id", flat=True)
        return sorted({*made, *signed_up, *chats})

    @staticmethod
    def list_owner_ids() -> list[int]:
        orphaned = ParleyConversation.objects.filter(
            encounter_id__isnull=False
        ).values_list("encounter_id", flat=True)
        return sorted({*Encounter.objects.values_list("pk", flat=True), *orphaned})

    @staticmethod
    def list_chat_ids() -> list[int]:
        return _chat_ids(Q(encounter_id__isnull=False))

    @staticmethod
    def chat_id(owner_id: int) -> int | None:
        return (
            ParleyConversation.objects.filter(encounter_id=owner_id)
            .values_list("pk", flat=True)
            .first()
        )


class BoardChatRepository(ParleyOwnedChatRepositoryProtocol):
    kind = ParleyConversationKind.BOARD

    @staticmethod
    def lock(owner_id: int) -> None:
        list(Board.objects.select_for_update().filter(pk=owner_id).values_list("pk"))

    @staticmethod
    def list_candidates(owner_id: int) -> list[ParleyChatCandidate]:
        # Nobody while the board's sphere has chat off, or once it is gone.
        creator_id = (
            Board.objects.filter(pk=owner_id, sphere__parley_enabled=True)
            .values_list("creator_id", flat=True)
            .first()
        )
        if creator_id is None:
            return []
        visitors = BoardVisit.objects.filter(board_id=owner_id).values("user_id")
        return _candidates(Q(pk=creator_id) | Q(pk__in=visitors))

    @staticmethod
    def set_members(*, owner_id: int, user_ids: list[int]) -> int | None:
        chat = ParleyConversation.objects.filter(board_id=owner_id).first()
        if chat is None and user_ids and Board.objects.filter(pk=owner_id).exists():
            chat = ParleyConversation.objects.create(
                kind=ParleyConversationKind.BOARD, board_id=owner_id
            )
        return _replace_members(chat, user_ids)

    @staticmethod
    def owner_ids_of(user_id: int) -> list[int]:
        made = Board.objects.filter(creator_id=user_id).values_list("pk", flat=True)
        visited = BoardVisit.objects.filter(user_id=user_id).values_list(
            "board_id", flat=True
        )
        chats = ParleyConversationMember.objects.filter(
            user_id=user_id, conversation__board_id__isnull=False
        ).values_list("conversation__board_id", flat=True)
        return sorted({*made, *visited, *chats})

    @staticmethod
    def list_owner_ids() -> list[int]:
        orphaned = ParleyConversation.objects.filter(
            board_id__isnull=False
        ).values_list("board_id", flat=True)
        return sorted({*Board.objects.values_list("pk", flat=True), *orphaned})

    @staticmethod
    def list_chat_ids() -> list[int]:
        return _chat_ids(Q(board_id__isnull=False))

    @staticmethod
    def chat_id(owner_id: int) -> int | None:
        return (
            ParleyConversation.objects.filter(board_id=owner_id)
            .values_list("pk", flat=True)
            .first()
        )
