from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING

from django.utils.formats import date_format, time_format
from django.utils.text import Truncator
from django.utils.timezone import localtime

from ludamus.gates.web.django.entities import UserInfo
from ludamus.pacts import EncounterRSVPDTO, NotFoundError, UnitOfWorkProtocol

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ludamus.pacts import EncounterDTO

ENCOUNTER_DESCRIPTION_WORDS = 25


def encounter_meta_description(encounter: EncounterDTO) -> str:
    start = localtime(encounter.start_time)
    head = f"{date_format(start)}, {time_format(start)}"
    if encounter.place:
        head = f"{head} — {encounter.place}"
    if not encounter.description:
        return head
    summary = Truncator(encounter.description).words(ENCOUNTER_DESCRIPTION_WORDS)
    return f"{head} | {summary}"


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
