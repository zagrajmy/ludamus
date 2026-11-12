from __future__ import annotations

import logging
from secrets import token_urlsafe
from typing import TYPE_CHECKING

from ludamus.mills.parley_conversations import visible_conversations
from ludamus.pacts.parley import (
    REVOKE_EVERYONE,
    ParleyAgeGate,
    ParleyBootstrapDTO,
    ParleyCapabilityClaims,
    ParleyConversationRepositoryProtocol,
    ParleyMembershipOutboxProtocol,
    ParleyMemberState,
    ParleyMessageLookupClaims,
    ParleyMessageReaderProtocol,
    ParleyReportData,
    ParleyReportRecord,
    ParleyRepositoryProtocol,
    ParleyRevocationClaims,
    ParleyRevocationOutboxProtocol,
    ParleyRevocationServiceProtocol,
    ParleyRoomGrant,
    ParleyRoomKind,
    ParleySignerProtocol,
    ParleyTimeWindow,
    ParleyWorkerUnavailableError,
)
from ludamus.pacts.user import AgeBand
from ludamus.specs.parley import (
    PARLEY_MESSAGE_LIFETIME,
    PARLEY_SESSION_READ_ONLY_DELAY,
    PARLEY_SESSION_RETENTION,
    PARLEY_TOKEN_LIFETIME,
)

if TYPE_CHECKING:
    from datetime import datetime

    from ludamus.pacts.parley import (
        ParleyConversationDTO,
        ParleyPartyChatProtocol,
        ParleyRoomDTO,
    )

logger = logging.getLogger(__name__)

_CONVERSATION = "conversation:"
# A lookup is signed for the one call that carries it.
_LOOKUP_LIFETIME_SECONDS = 60
_AGE_GATES = {
    AgeBand.UNKNOWN: ParleyAgeGate.UNCONFIRMED,
    AgeBand.THIRTEEN_TO_FIFTEEN: ParleyAgeGate.UNDER_16,
}


def _grants(
    rooms: list[ParleyRoomDTO], kind: ParleyRoomKind
) -> dict[str, ParleyRoomGrant]:
    return {
        room.name: ParleyRoomGrant(ends_at=room.ends_at, writable=room.can_write)
        for room in rooms
        if room.kind == kind and not room.can_moderate and room.ends_at is not None
    }


class ParleyService:
    """One pass, and one list of chats, across every sphere someone is in."""

    def __init__(
        self,
        *,
        repository: ParleyRepositoryProtocol,
        conversations: ParleyConversationRepositoryProtocol,
        party_chats: ParleyPartyChatProtocol,
        signer: ParleySignerProtocol,
        messages: ParleyMessageReaderProtocol,
        agent_host: str,
    ) -> None:
        self._repository = repository
        self._conversations = conversations
        self._party_chats = party_chats
        self._signer = signer
        self._messages = messages
        self._agent_host = agent_host

    def is_open_to(self, *, user_id: int, now: datetime) -> bool:
        """Whether this person has anywhere to chat at all."""
        return (
            self._conversations.is_eligible(user_id)
            or self._repository.has_rooms(user_id=user_id, window=self._window(now))
            or bool(self._visible_conversations(user_id, direct=False))
        )

    def bootstrap(self, *, user_id: int, now: datetime) -> ParleyBootstrapDTO | None:
        access = self._repository.read_access(user_id=user_id, window=self._window(now))
        if access is None:
            return None
        direct = self._conversations.is_eligible(user_id)
        self._party_chats.sync_member(user_id)
        conversations = self._visible_conversations(user_id, direct=direct)
        if not (direct or access.rooms or conversations):
            return None

        issued_at = int(now.timestamp())
        claims = ParleyCapabilityClaims(
            iss="ludamus",
            aud="parley",
            sub=str(access.user_id),
            name=access.user_name,
            avatar=access.user_avatar_url,
            managed=[str(sphere_id) for sphere_id in access.managed_sphere_ids],
            sessions=_grants(access.rooms, ParleyRoomKind.SESSION),
            events=_grants(access.rooms, ParleyRoomKind.EVENT),
            read_only_after=int(PARLEY_SESSION_READ_ONLY_DELAY.total_seconds()),
            retain_for=int(PARLEY_SESSION_RETENTION.total_seconds()),
            direct=direct,
            iat=issued_at,
            exp=int((now + PARLEY_TOKEN_LIFETIME).timestamp()),
            jti=token_urlsafe(18),
        )
        logger.info(
            "parley pass issued: user=%s rooms=%s conversations=%s managed=%s",
            access.user_id,
            len(access.rooms),
            len(conversations),
            len(access.managed_sphere_ids),
        )
        return ParleyBootstrapDTO(
            user={
                "id": str(access.user_id),
                "name": access.user_name,
                "avatarUrl": access.user_avatar_url,
            },
            rooms=access.rooms,
            can_message=direct,
            age_gate=(
                None
                if direct
                else _AGE_GATES.get(self._conversations.read_age_band(user_id))
            ),
            conversations=conversations,
            blocked=self._conversations.list_blocked(user_id),
            capability_token=self._signer.sign(claims),
            agent_host=self._agent_host,
        )

    def report_message(self, *, data: ParleyReportData, now: datetime) -> bool:
        """Keep a report of a message the reporter can see and did not write.

        The room is asked for the message, so staff read what it said; a
        report stands without that copy when the room cannot be asked.
        """
        if data.room_id.startswith(_CONVERSATION):
            if (conversation_id := self._conversation_seen_by(data)) is None:
                return False
            sphere_id = None
        elif (sphere_id := self._sphere_of_room_seen_by(data, now)) is not None:
            conversation_id = None
        else:
            return False
        try:
            message = self._messages.read_message(self._lookup(data, now))
        except ParleyWorkerUnavailableError:
            logger.warning(
                "parley report kept without its message: room=%s message=%s",
                data.room_id,
                data.message_id,
            )
            message = None
        else:
            if message is None or message.author_id == str(data.user_id):
                return False
        self._repository.save_report(
            ParleyReportRecord(
                reporter_id=data.user_id,
                sphere_id=sphere_id,
                conversation_id=conversation_id,
                room_id=data.room_id,
                message_id=data.message_id,
                reason=data.reason,
                message=message,
            )
        )
        return True

    def _visible_conversations(
        self, user_id: int, *, direct: bool
    ) -> list[ParleyConversationDTO]:
        return visible_conversations(
            self._conversations.list_for(user_id), direct=direct
        )

    def _conversation_seen_by(self, data: ParleyReportData) -> int | None:
        # Anyone still in it, a request's recipient among them.
        key = data.room_id.removeprefix(_CONVERSATION)
        if not key.isdigit():
            return None
        member = self._conversations.read_member(
            conversation_id=int(key), user_id=data.user_id
        )
        present = (ParleyMemberState.ACTIVE, ParleyMemberState.REQUEST)
        return int(key) if member is not None and member[1] in present else None

    def _sphere_of_room_seen_by(
        self, data: ParleyReportData, now: datetime
    ) -> int | None:
        access = self._repository.read_access(
            user_id=data.user_id, window=self._window(now)
        )
        if access is None or data.room_id not in {room.id for room in access.rooms}:
            return None
        return int(data.room_id.split(":")[1])

    def _lookup(self, data: ParleyReportData, now: datetime) -> str:
        issued_at = int(now.timestamp())
        return self._signer.sign(
            ParleyMessageLookupClaims(
                iss="ludamus",
                aud="parley-message",
                room=data.room_id,
                message=data.message_id,
                iat=issued_at,
                exp=issued_at + _LOOKUP_LIFETIME_SECONDS,
                jti=token_urlsafe(18),
            )
        )

    @staticmethod
    def _window(now: datetime) -> ParleyTimeWindow:
        return ParleyTimeWindow(
            now=now,
            retained_after=now - PARLEY_SESSION_RETENTION,
            writable_after=now - PARLEY_SESSION_READ_ONLY_DELAY,
        )


class ParleyReportRetentionService:
    """Let a report's copy of a message go when the message itself does.

    Rooms delete every message a year after it was written. The report stays
    as the moderation record: who reported whom, why, and when it was written.
    """

    def __init__(self, *, repository: ParleyRepositoryProtocol) -> None:
        self._repository = repository

    def forget_expired_copies(self, *, now: datetime) -> int:
        return self._repository.forget_copies_written_before(
            now - PARLEY_MESSAGE_LIFETIME
        )


class ParleyRevocationService(ParleyRevocationServiceProtocol):
    """Tell the Worker to drop passes Django would no longer issue.

    A pass lives for hours so the chat keeps working while Django is away,
    which leaves taking access back to these pushes. Each one forces the
    person to fetch a new pass, which then reflects the change.
    """

    def __init__(
        self,
        *,
        repository: ParleyRepositoryProtocol,
        outbox: ParleyRevocationOutboxProtocol,
        conversations: ParleyConversationRepositoryProtocol,
        memberships: ParleyMembershipOutboxProtocol,
    ) -> None:
        self._repository = repository
        self._outbox = outbox
        self._conversations = conversations
        self._memberships = memberships

    def revoke_event_user(self, *, event_id: int, user_id: int) -> None:
        if (sphere_id := self._repository.read_event_sphere_id(event_id)) is not None:
            self._outbox.schedule(sphere_ids=[sphere_id], subject=str(user_id))

    def revoke_user(self, *, user_id: int) -> None:
        if sphere_ids := self._repository.list_chat_sphere_ids():
            self._outbox.schedule(sphere_ids=sphere_ids, subject=str(user_id))
        # Their conversations drop them from the member list the Worker holds.
        self._memberships.schedule(
            conversation_ids=self._conversations.conversation_ids_of(user_id)
        )

    def revoke_sphere(self, *, sphere_id: int) -> None:
        self._outbox.schedule(sphere_ids=[sphere_id], subject=REVOKE_EVERYONE)

    def revoke_event(self, *, event_id: int) -> None:
        if (sphere_id := self._repository.read_event_sphere_id(event_id)) is not None:
            self._outbox.schedule(sphere_ids=[sphere_id], subject=REVOKE_EVERYONE)


def sign_revocations(
    *, signer: ParleySignerProtocol, sphere_ids: list[int], subject: str, now: datetime
) -> list[str]:
    cutoff = int(now.timestamp())
    expires_at = int((now + PARLEY_TOKEN_LIFETIME).timestamp())
    return [
        signer.sign(
            ParleyRevocationClaims(
                iss="ludamus",
                aud="parley-revocation",
                sphere=str(sphere_id),
                sub=subject,
                revoked_before=cutoff,
                iat=cutoff,
                exp=expires_at,
                jti=token_urlsafe(18),
            )
        )
        for sphere_id in sphere_ids
    ]
