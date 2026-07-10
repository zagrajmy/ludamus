# Builds the organizer event-ban "fake-full" illusion: a banned viewer sees
# every session as full with simulacra players and no Enroll action. We build a
# fresh "full" copy of each SessionData rather than mutating the read path.
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from ludamus.adapters.web.django.entities import ParticipationInfo, SessionData
from ludamus.gates.web.django.entities import UserInfo
from ludamus.pacts.legacy import SessionParticipationStatus

_SIMULACRA_FILL = 8
_SIMULACRA_NAMES = ("Aleksandra Nowak", "Piotr Kowalski", "Maria Wiśniewska")


def _simulacra_participations(count: int) -> list[ParticipationInfo]:
    now = datetime.now(tz=UTC)
    return [
        ParticipationInfo(
            user=UserInfo(
                avatar_url=None,
                discord_username="",
                full_name=name,
                name=name,
                # Negative pk: clearly synthetic, never collides with a real user.
                pk=-index - 1,
                slug="",
                username="",
            ),
            status=SessionParticipationStatus.CONFIRMED.value,
            creation_time=now,
        )
        for index, name in enumerate(_SIMULACRA_NAMES[:count])
    ]


def fake_full_card(session_data: SessionData) -> SessionData:
    # A full-looking copy of session_data with simulacra players.
    fill = session_data.effective_participants_limit or _SIMULACRA_FILL
    return replace(
        session_data,
        effective_participants_limit=fill,
        enrolled_count=fill,
        waiting_count=0,
        is_full=True,
        is_enrollment_available=True,
        full_participant_info=f"{fill}/{fill}",
        user_enrolled=False,
        user_waiting=False,
        session_participations=_simulacra_participations(min(3, fill)),
    )
