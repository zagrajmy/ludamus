"""Splitting a session's offered times into what each table stores."""

from typing import TYPE_CHECKING

from ludamus.links.db.django.models import TimeSlot
from ludamus.pacts.errors import NotFoundError

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import date

    from ludamus.pacts.availability import AvailabilityDTO


def split_offers(
    offered: Iterable[AvailabilityDTO],
) -> tuple[set[tuple[date, str]], set[int]]:
    parts: set[tuple[date, str]] = set()
    slot_pks: set[int] = set()
    for entry in offered:
        if entry.time_slot is not None:
            slot_pks.add(entry.time_slot.pk)
        elif entry.part is not None:
            parts.add((entry.day, str(entry.part)))
    return parts, slot_pks


def event_slot_pks(*, event_id: int, slot_pks: set[int]) -> list[int]:
    # A slot belongs to one event, so a pk from another one is refused before
    # anything is written rather than linked across events.
    owned = list(
        TimeSlot.objects.filter(event_id=event_id, pk__in=slot_pks).values_list(
            "pk", flat=True
        )
    )
    if len(owned) != len(slot_pks):
        msg = "Time slot not found in this event"
        raise NotFoundError(msg)
    return owned
