from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ludamus.pacts.chronology import SessionCardStatsDTO

_SIMULACRA_FILL = 8


def fake_full_seats(seats: SessionCardStatsDTO) -> SessionCardStatsDTO:
    # Every seat taken, nobody waiting. Left at a limit of 0 the session would
    # read as taking no enrollment instead of the "Full" the mask exists for.
    fill = seats.effective_participants_limit or _SIMULACRA_FILL
    return seats.model_copy(
        update={
            "participants_limit": fill,
            "seating_percentage": None,
            "enrolled_count": fill,
            "waiting_count": 0,
        }
    )
