from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ludamus.gates.web.django.chronology.event_presentation import SessionData
    from ludamus.pacts import FacilitatorListItemDTO
    from ludamus.pacts.guild import GuildServiceProtocol


def attach_guild_marks(
    sessions_data: dict[int, SessionData],
    *,
    guilds: GuildServiceProtocol,
    sphere_id: int,
) -> None:
    # One query for the whole page: the mark hangs off the person on the
    # card, so a per-card lookup would be an N+1.
    if not sessions_data:
        return
    marks = guilds.marks_for_sessions(
        sphere_id=sphere_id, session_pks=list(sessions_data)
    )
    for session_pk, data in sessions_data.items():
        data.guild = marks.get(session_pk)


def attach_facilitator_guild_marks(
    facilitators: Sequence[FacilitatorListItemDTO],
    *,
    guilds: GuildServiceProtocol,
    sphere_id: int,
) -> None:
    # Same one-query-per-page shape as the card version above.
    if not facilitators:
        return
    marks = guilds.marks_for_facilitators(
        sphere_id=sphere_id,
        facilitator_pks=[facilitator.pk for facilitator in facilitators],
    )
    for facilitator in facilitators:
        facilitator.guild = marks.get(facilitator.pk)
