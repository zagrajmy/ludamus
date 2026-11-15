"""Splitting a session's offered times into what each table stores."""

from typing import TYPE_CHECKING

from ludamus.links.db.django.models import TimeSlot
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.event import TimeSlotDTO

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
        if isinstance(offer := entry.offer, TimeSlotDTO):
            slot_pks.add(offer.pk)
        else:
            parts.add((entry.day, str(offer)))
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
