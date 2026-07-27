from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING

from ludamus.gates.web.django.entities import UserInfo
from ludamus.pacts import EncounterRSVPDTO, NotFoundError, UnitOfWorkProtocol

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


def build_attendee_list(
    rsvps: Sequence[EncounterRSVPDTO],
    uow: UnitOfWorkProtocol,
    gravatar_url: Callable[[str], str | None],
) -> list[UserInfo]:
    attendees: list[UserInfo] = []
    for rsvp in rsvps:
        with suppress(NotFoundError):
            attendees.append(
                UserInfo.from_user_dto(
                    uow.active_users.read_by_id(rsvp.user_id), gravatar_url=gravatar_url
                )
            )
    return attendees
