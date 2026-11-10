from __future__ import annotations

from secrets import token_urlsafe
from typing import TYPE_CHECKING

from ludamus.pacts.parley import (
    REVOKE_EVERYONE,
    ParleyBootstrapDTO,
    ParleyCapabilityClaims,
    ParleyConversationRepositoryProtocol,
    ParleyReportData,
    ParleyRepositoryProtocol,
    ParleyRevocationClaims,
    ParleyRevocationOutboxProtocol,
    ParleyRevocationServiceProtocol,
    ParleyRole,
    ParleySessionGrant,
    ParleySignerProtocol,
    ParleyTimeWindow,
)
from ludamus.specs.parley import (
    PARLEY_SESSION_READ_ONLY_DELAY,
    PARLEY_SESSION_RETENTION,
    PARLEY_TOKEN_LIFETIME,
)

if TYPE_CHECKING:
    from datetime import datetime


class ParleyService:
    def __init__(
        self,
        *,
        repository: ParleyRepositoryProtocol,
        conversations: ParleyConversationRepositoryProtocol,
        signer: ParleySignerProtocol,
        agent_host: str,
    ) -> None:
        self._repository = repository
        self._conversations = conversations
        self._signer = signer
        self._agent_host = agent_host

    def bootstrap(
        self, *, sphere_id: int, user_id: int, now: datetime
    ) -> ParleyBootstrapDTO | None:
        access = self._repository.read_access(
            sphere_id=sphere_id, user_id=user_id, window=self._window(now)
        )
        if access is None:
            return None

        issued_at = int(now.timestamp())
        direct = self._conversations.is_eligible(user_id)
        claims = ParleyCapabilityClaims(
            iss="ludamus",
            aud="parley",
            sub=str(access.user_id),
            sphere=str(access.sphere_id),
            name=access.user_name,
            avatar=access.user_avatar_url,
            role=ParleyRole.MANAGER if access.is_manager else ParleyRole.MEMBER,
            sessions=(
                {}
                if access.is_manager
                else {
                    str(room.session_id): ParleySessionGrant(
                        ends_at=room.ends_at, writable=room.can_write
                    )
                    for room in access.rooms
                    if room.session_id is not None and room.ends_at is not None
                }
            ),
            read_only_after=int(PARLEY_SESSION_READ_ONLY_DELAY.total_seconds()),
            retain_for=int(PARLEY_SESSION_RETENTION.total_seconds()),
            direct=direct,
            iat=issued_at,
            exp=int((now + PARLEY_TOKEN_LIFETIME).timestamp()),
            jti=token_urlsafe(18),
        )
        return ParleyBootstrapDTO(
            sphere={"id": str(access.sphere_id), "name": access.sphere_name},
            user={
                "id": str(access.user_id),
                "name": access.user_name,
                "avatarUrl": access.user_avatar_url,
            },
            rooms=access.rooms,
            conversations=self._conversations.list_for(user_id) if direct else [],
            capability_token=self._signer.sign(claims),
            agent_host=self._agent_host,
        )

    def report_message(self, *, data: ParleyReportData, now: datetime) -> bool:
        return self._repository.create_report(data=data, window=self._window(now))

    @staticmethod
    def _window(now: datetime) -> ParleyTimeWindow:
        return ParleyTimeWindow(
            now=now,
            retained_after=now - PARLEY_SESSION_RETENTION,
            writable_after=now - PARLEY_SESSION_READ_ONLY_DELAY,
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
    ) -> None:
        self._repository = repository
        self._outbox = outbox

    def revoke_event_user(self, *, event_id: int, user_id: int) -> None:
        if (sphere_id := self._repository.read_event_sphere_id(event_id)) is not None:
            self._outbox.schedule(sphere_ids=[sphere_id], subject=str(user_id))

    def revoke_user(self, *, user_id: int) -> None:
        if sphere_ids := self._repository.list_chat_sphere_ids():
            self._outbox.schedule(sphere_ids=sphere_ids, subject=str(user_id))

    def revoke_sphere(self, *, sphere_id: int) -> None:
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
