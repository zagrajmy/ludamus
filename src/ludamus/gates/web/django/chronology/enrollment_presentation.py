from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ludamus.pacts.crowd import UserDTO


@dataclass(frozen=True)
class PartyMemberFlags:
    is_member: bool = False
    needs_accept: bool = False
    blocked: bool = False


@dataclass
class SessionUserParticipationData:
    user: UserDTO
    user_enrolled: bool = False
    user_waiting: bool = False
    seat_held: bool = False
    offer_pending: bool = False
    has_time_conflict: bool = False
    membership: PartyMemberFlags = PartyMemberFlags()
