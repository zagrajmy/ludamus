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
    # One query for the whole page: the mark hangs off the presenter's guild
    # membership, so a per-card lookup would be an N+1. Presenter-less sessions
    # carry pk 0 and are skipped, so a page of them costs no query at all.
    presenter_pks = [
        data.presenter.pk for data in sessions_data.values() if data.presenter.pk
    ]
    if not presenter_pks:
        return
    marks = guilds.marks_for_users(sphere_id=sphere_id, user_pks=presenter_pks)
    for data in sessions_data.values():
        data.guild = marks.get(data.presenter.pk)


def attach_facilitator_guild_marks(
    facilitators: Sequence[FacilitatorListItemDTO],
    *,
    guilds: GuildServiceProtocol,
    sphere_id: int,
) -> None:
    # Same one-query-per-page shape as the card version above. Membership hangs
    # off the linked user, and a facilitator imported from a spreadsheet has
    # none, so a page of import-created rows costs no query at all.
    if not (user_pks := [f.user_id for f in facilitators if f.user_id]):
        return
    marks = guilds.marks_for_users(sphere_id=sphere_id, user_pks=user_pks)
    for facilitator in facilitators:
        if facilitator.user_id:
            facilitator.guild = marks.get(facilitator.user_id)
