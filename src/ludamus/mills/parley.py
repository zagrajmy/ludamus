from __future__ import annotations

from secrets import token_urlsafe
from typing import TYPE_CHECKING

from ludamus.pacts.parley import (
    ParleyBootstrapDTO,
    ParleyCapabilityClaims,
    ParleyCapabilitySignerProtocol,
    ParleyReportData,
    ParleyRepositoryProtocol,
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
        signer: ParleyCapabilitySignerProtocol,
        agent_host: str,
    ) -> None:
        self._repository = repository
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
        claims = ParleyCapabilityClaims(
            iss="ludamus",
            aud="parley",
            sub=str(access.user_id),
            sphere=str(access.sphere_id),
            name=access.user_name,
            avatar=access.user_avatar_url,
            rooms=[room.id for room in access.rooms],
            writes=[room.id for room in access.rooms if room.can_write],
            moderates=access.moderated_room_ids,
            lifecycle={
                room.id: {"readOnlyAt": room.read_only_at, "deleteAt": room.delete_at}
                for room in access.rooms
                if room.read_only_at is not None and room.delete_at is not None
            },
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
            read_only_delay=PARLEY_SESSION_READ_ONLY_DELAY,
            retention=PARLEY_SESSION_RETENTION,
        )
