from __future__ import annotations

from contextlib import suppress
from html import unescape
from typing import TYPE_CHECKING

from django.utils.formats import date_format, time_format
from django.utils.html import strip_tags
from django.utils.text import Truncator
from django.utils.timezone import localtime

from ludamus.gates.web.django.entities import UserInfo
from ludamus.pacts import EncounterRSVPDTO, NotFoundError, UnitOfWorkProtocol

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ludamus.pacts import EncounterDTO


SUMMARY_WORDS = 20


def encounter_meta_description(encounter: EncounterDTO, description_html: str) -> str:
    start = localtime(encounter.start_time)
    parts = [f"{date_format(start)}, {time_format(start)}"]
    if encounter.place:
        parts.append(f"— {encounter.place}")
    if description_html:
        summary = unescape(strip_tags(description_html))
        parts.append(f"| {Truncator(summary).words(SUMMARY_WORDS)}")
    return " ".join(parts)


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
