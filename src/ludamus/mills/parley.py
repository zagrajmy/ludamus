from __future__ import annotations

import logging
from secrets import token_urlsafe
from typing import TYPE_CHECKING

from ludamus.mills.parley_conversations import visible_conversations
from ludamus.pacts.parley import (
    CONVERSATION_POLICIES,
    REVOKE_EVERYONE,
    ParleyAgeGate,
    ParleyBootstrapDTO,
    ParleyCapabilityClaims,
    ParleyConversationRepositoryProtocol,
    ParleyEventGrant,
    ParleyManagedSphere,
    ParleyMembershipOutboxProtocol,
    ParleyMemberState,
    ParleyMessageLookupClaims,
    ParleyMessageReaderProtocol,
    ParleyModerationResult,
    ParleyReportData,
    ParleyReportRecord,
    ParleyRepositoryProtocol,
    ParleyRevocationClaims,
    ParleyRevocationOutboxProtocol,
    ParleyRevocationServiceProtocol,
    ParleyRoomKind,
    ParleySignerProtocol,
    ParleyTimeWindow,
    ParleyWorkerUnavailableError,
)
from ludamus.pacts.sphere import Capability
from ludamus.pacts.user import AgeBand
from ludamus.specs.parley import (
    PARLEY_MESSAGE_LIFETIME,
    PARLEY_PASS_MAX_LENGTH,
    PARLEY_SESSION_READ_ONLY_DELAY,
    PARLEY_SESSION_RETENTION,
    PARLEY_TOKEN_LIFETIME,
)
from ludamus.specs.permissions import sphere_access

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from ludamus.pacts.parley import ParleyPartyChatProtocol, ParleyRoomDTO

logger = logging.getLogger(__name__)

_CONVERSATION = "conversation:"
# A lookup is signed for the one call that carries it.
_LOOKUP_LIFETIME_SECONDS = 60
_AGE_GATES = {
    AgeBand.UNKNOWN: ParleyAgeGate.UNCONFIRMED,
    AgeBand.THIRTEEN_TO_FIFTEEN: ParleyAgeGate.UNDER_16,
}
# Conversations someone may be in whether or not direct messages are open.
_OPEN_KINDS = frozenset(
    kind for kind, policy in CONVERSATION_POLICIES.items() if not policy.needs_direct
)


def _event_key(room: ParleyRoomDTO) -> str:
    event_pk = room.pk if room.kind == ParleyRoomKind.EVENT else room.event_pk
    return f"{room.sphere_id}:{event_pk}"


def _granted(room: ParleyRoomDTO) -> bool:
    # NOTE: moderators reach a sphere's programme points through `managed`, so
    # their pass does not grow with the programme; an event grant still
    # carries when its chat ends and whether it is open at all.
    if room.kind == ParleyRoomKind.SESSION:
        return not room.can_moderate
    return room.kind == ParleyRoomKind.EVENT


def _event_grants(rooms: list[ParleyRoomDTO]) -> dict[str, ParleyEventGrant]:
    grants: dict[str, ParleyEventGrant] = {}
    for room in [room for room in rooms if _granted(room)]:
        grant = grants.setdefault(
            _event_key(room),
            ParleyEventGrant(
                ends_at=room.ends_at or 0, writable=False, chat=False, sessions={}
            ),
        )
        if room.kind == ParleyRoomKind.EVENT:
            grant.chat = True
            grant.writable = room.can_write
        else:
            grant.sessions[str(room.pk)] = room.can_write
    return grants


def _managed(
    rooms: list[ParleyRoomDTO], moderated: frozenset[int]
) -> dict[str, ParleyManagedSphere]:
    open_rooms = {
        room.sphere_id for room in rooms if room.kind == ParleyRoomKind.ORGANIZERS
    }
    return {
        str(sphere_id): ParleyManagedSphere(organizers=sphere_id in open_rooms)
        for sphere_id in sorted(moderated)
    }


def _fitted(
    rooms: list[ParleyRoomDTO], fits: Callable[[list[ParleyRoomDTO]], bool]
) -> list[ParleyRoomDTO]:
    """Drop the rooms of the events ending first until the pass fits.

    A browser silently drops a cookie past its size, so a pass that cannot
    fit them all keeps the events still ahead.
    """
    ends = {_event_key(room): room.ends_at or 0 for room in rooms if _granted(room)}
    dropped: set[str] = set()
    kept = rooms
    for key in sorted(ends, key=ends.__getitem__):
        if fits(kept):
            break
        dropped.add(key)
        kept = [
            room
            for room in rooms
            if not _granted(room) or _event_key(room) not in dropped
        ]
    return kept


class ParleyService:
    """One pass, and one list of chats, across every sphere someone is in."""

    def __init__(
        self,
        *,
        repository: ParleyRepositoryProtocol,
        conversations: ParleyConversationRepositoryProtocol,
        signer: ParleySignerProtocol,
        messages: ParleyMessageReaderProtocol,
        agent_host: str,
    ) -> None:
        self._repository = repository
        self._conversations = conversations
        self._signer = signer
        self._messages = messages
        self._agent_host = agent_host

    def is_open_to(self, *, user_id: int, now: datetime) -> bool:
        """Whether this person has anywhere to chat at all."""
        return (
            self._conversations.is_eligible(user_id)
            or self._repository.has_rooms(
                user_id=user_id,
                window=self._window(now),
                moderated=self._moderated(user_id),
            )
            or self._conversations.has_conversation(user_id=user_id, kinds=_OPEN_KINDS)
        )

    def bootstrap(self, *, user_id: int, now: datetime) -> ParleyBootstrapDTO | None:
        moderated = self._moderated(user_id)
        access = self._repository.read_access(
            user_id=user_id, window=self._window(now), moderated=moderated
        )
        if access is None:
            return None
        direct = self._conversations.is_eligible(user_id)
        conversations = visible_conversations(
            self._conversations.list_for(user_id), direct=direct
        )
        if not (direct or access.rooms or conversations):
            return None

        issued_at = int(now.timestamp())

        def sign(rooms: list[ParleyRoomDTO]) -> str:
            return self._signer.sign(
                ParleyCapabilityClaims(
                    iss="ludamus",
                    aud="parley",
                    sub=str(access.user_id),
                    name=access.user_name,
                    avatar=access.user_avatar_url,
                    managed=_managed(rooms, moderated),
                    events=_event_grants(rooms),
                    read_only_after=int(PARLEY_SESSION_READ_ONLY_DELAY.total_seconds()),
                    retain_for=int(PARLEY_SESSION_RETENTION.total_seconds()),
                    direct=direct,
                    iat=issued_at,
                    exp=int((now + PARLEY_TOKEN_LIFETIME).timestamp()),
                    jti=token_urlsafe(18),
                )
            )

        rooms = _fitted(
            access.rooms, lambda kept: len(sign(kept)) <= PARLEY_PASS_MAX_LENGTH
        )
        if len(rooms) < len(access.rooms):
            logger.error(
                "parley pass over its size: user=%s kept=%s of %s rooms",
                access.user_id,
                len(rooms),
                len(access.rooms),
            )
        logger.info(
            "parley pass issued: user=%s rooms=%s conversations=%s managed=%s",
            access.user_id,
            len(rooms),
            len(conversations),
            len(moderated),
        )
        return ParleyBootstrapDTO(
            user={
                "id": str(access.user_id),
                "name": access.user_name,
                "avatarUrl": access.user_avatar_url,
            },
            rooms=rooms,
            can_message=direct,
            age_gate=(
                None
                if direct
                else _AGE_GATES.get(self._conversations.read_age_band(user_id))
            ),
            conversations=conversations,
            blocked=self._conversations.list_blocked(user_id),
            capability_token=sign(rooms),
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
        elif (room := self._room_seen_by(data, now)) is not None:
            conversation_id, sphere_id = None, room.sphere_id
        else:
            return False
        try:
            message = self._messages.read_message(
                self._lookup(
                    room_id=data.room_id,
                    message_id=data.message_id,
                    audience="parley-message",
                    now=now,
                )
            )
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

    def delete_reported(
        self, *, report_ids: list[int], now: datetime
    ) -> ParleyModerationResult:
        """Delete each reported message for everyone, as staff, and resolve it.

        A message whose room does not answer stays reported.
        """
        deleted = failed = 0
        for ref in self._repository.list_reported(report_ids):
            try:
                self._messages.moderate(
                    self._lookup(
                        room_id=ref.room_id,
                        message_id=ref.message_id,
                        audience="parley-moderation",
                        now=now,
                    )
                )
            except ParleyWorkerUnavailableError:
                logger.exception(
                    "parley staff deletion failed: room=%s message=%s",
                    ref.room_id,
                    ref.message_id,
                )
                failed += 1
                continue
            self._repository.resolve_reports(
                room_id=ref.room_id, message_id=ref.message_id, now=now
            )
            logger.info(
                "parley message deleted by staff: room=%s message=%s",
                ref.room_id,
                ref.message_id,
            )
            deleted += 1
        return ParleyModerationResult(deleted=deleted, failed=failed)

    def _moderated(self, user_id: int) -> frozenset[int]:
        return frozenset(
            seat.sphere_id
            for seat in self._repository.list_team_seats(user_id)
            if sphere_access(seat.role, is_superuser=False).allows(
                Capability.CHAT_MODERATE
            )
        )

    def _conversation_seen_by(self, data: ParleyReportData) -> int | None:
        key = data.room_id.removeprefix(_CONVERSATION)
        if not key.isdigit():
            return None
        member = self._conversations.read_member(
            conversation_id=int(key), user_id=data.user_id
        )
        present = (ParleyMemberState.ACTIVE, ParleyMemberState.REQUEST)
        return int(key) if member is not None and member.state in present else None

    def _room_seen_by(
        self, data: ParleyReportData, now: datetime
    ) -> ParleyRoomDTO | None:
        access = self._repository.read_access(
            user_id=data.user_id,
            window=self._window(now),
            moderated=self._moderated(data.user_id),
        )
        rooms = [] if access is None else access.rooms
        return next((room for room in rooms if room.id == data.room_id), None)

    def _lookup(
        self, *, room_id: str, message_id: int, audience: str, now: datetime
    ) -> str:
        issued_at = int(now.timestamp())
        return self._signer.sign(
            ParleyMessageLookupClaims(
                iss="ludamus",
                aud=audience,
                room=room_id,
                message=message_id,
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
        party_chats: ParleyPartyChatProtocol,
    ) -> None:
        self._repository = repository
        self._outbox = outbox
        self._conversations = conversations
        self._memberships = memberships
        self._party_chats = party_chats

    def revoke_event_user(self, *, event_id: int, user_id: int) -> None:
        if (sphere_id := self._repository.read_event_sphere_id(event_id)) is not None:
            self._outbox.schedule(sphere_ids=[sphere_id], subject=str(user_id))

    def revoke_user(self, *, user_id: int) -> None:
        if sphere_ids := self._repository.list_chat_sphere_ids():
            self._outbox.schedule(sphere_ids=sphere_ids, subject=str(user_id))
        self.age_changed(user_id=user_id)

    def age_changed(self, *, user_id: int) -> None:
        # Who may be in their conversations, and their parties' chats, can
        # hang on their age; the Worker hears each list again.
        self._memberships.schedule(
            conversation_ids=self._conversations.conversation_ids_of(user_id)
        )
        self._party_chats.sync_parties_of(user_id)

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
