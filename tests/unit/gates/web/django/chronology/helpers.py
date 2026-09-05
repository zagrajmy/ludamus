"""Builders shared by the chronology presentation and room-lane unit tests."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from ludamus.gates.web.django.chronology.event_presentation import SessionData
from ludamus.pacts import NO_LOCATION

if TYPE_CHECKING:
    from ludamus.gates.web.django.chronology.schedule import RoomLanes, RoomLaneTile


def positioned_room_tiles(lanes: RoomLanes) -> list[tuple[int, RoomLaneTile]]:
    return [
        (row_index, tile)
        for row_index, row in enumerate(lanes.rows, start=1)
        for tile in row.starting_tiles
    ]


def room_tiles(lanes: RoomLanes) -> list[RoomLaneTile]:
    return [tile for _, tile in positioned_room_tiles(lanes)]


def make_session_data(
    effective_participants_limit: int = 10, enrolled_count: int = 0, **overrides
) -> SessionData:
    defaults = {
        "agenda_item": MagicMock(),
        "is_enrollment_available": True,
        "presenter": MagicMock(),
        "session": MagicMock(),
        "is_full": enrolled_count >= effective_participants_limit,
        "effective_participants_limit": effective_participants_limit,
        "enrolled_count": enrolled_count,
        "session_participations": [],
        "loc": MagicMock(),
    }
    return SessionData(**(defaults | overrides))


def location(**overrides):
    return {**NO_LOCATION, **overrides}
