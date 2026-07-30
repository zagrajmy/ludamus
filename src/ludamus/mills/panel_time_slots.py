from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.pacts.event import PanelTimeSlotsServiceProtocol, TimeSlotValidationError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from ludamus.pacts.legacy import (
        DateTimeRangeProtocol,
        EventDTO,
        TimeSlotDTO,
        TimeSlotRepositoryProtocol,
    )
    from ludamus.pacts.services import TransactionProtocol

# TODO(hasparus): fold-back plan for the legacy strangler, blocked while
# open PRs hold mills/legacy.py:
#   1. delete PanelService.validate_time_slot from mills/legacy.py (its logic
#      moved to _validate_time_slot below) and drop its vulture entry,
#   2. delete PanelService.delete_time_slot and its vulture entry,
#   3. fold this module into the event noun module so pacts/event.py and
#      mills/event.py mirror each other and the name stops colliding with
#      mills/timeslots.py.


def _validate_time_slot(
    *,
    start: datetime,
    end: datetime,
    event: EventDTO,
    existing_slots: Sequence[DateTimeRangeProtocol],
) -> list[TimeSlotValidationError]:
    errors: list[TimeSlotValidationError] = []

    if start >= end:
        errors.append(TimeSlotValidationError.START_NOT_BEFORE_END)

    if start < event.start_time or end > event.end_time:
        errors.append(TimeSlotValidationError.OUTSIDE_EVENT_DATES)

    if any(start < slot.end_time and end > slot.start_time for slot in existing_slots):
        errors.append(TimeSlotValidationError.OVERLAPS_EXISTING_SLOT)

    return errors


class PanelTimeSlotsService(PanelTimeSlotsServiceProtocol):
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        time_slots: TimeSlotRepositoryProtocol,
    ) -> None:
        self._transaction = transaction
        self._time_slots = time_slots

    def list_for_event(self, event_id: int) -> list[TimeSlotDTO]:
        return self._time_slots.list_by_event(event_id)

    def read(self, *, event_id: int, pk: int) -> TimeSlotDTO:
        return self._time_slots.read_by_event(event_id, pk)

    def create(
        self, *, event: EventDTO, start_time: datetime, end_time: datetime
    ) -> list[TimeSlotValidationError]:
        # atomic() keeps the write consistent but does not serialize the
        # check-then-insert: two concurrent requests can both read the same
        # slots, both pass validation, and insert overlapping slots. Full
        # enforcement needs a DB exclusion constraint on the slot range.
        with self._transaction.atomic():
            existing = self._time_slots.list_by_event(event.pk)
            errors = _validate_time_slot(
                start=start_time, end=end_time, event=event, existing_slots=existing
            )
            if not errors:
                self._time_slots.create(event.pk, start_time, end_time)
            return errors

    def update(
        self, *, event: EventDTO, pk: int, start_time: datetime, end_time: datetime
    ) -> list[TimeSlotValidationError]:
        # Same unserialized check-then-write race as in create().
        with self._transaction.atomic():
            # Scope the pk to the panel's event before writing; a foreign pk
            # raises NotFoundError with no side effects.
            self._time_slots.read_by_event(event.pk, pk)
            existing = [
                slot
                for slot in self._time_slots.list_by_event(event.pk)
                if slot.pk != pk
            ]
            errors = _validate_time_slot(
                start=start_time, end=end_time, event=event, existing_slots=existing
            )
            if not errors:
                self._time_slots.update(pk, start_time, end_time)
            return errors

    def delete(self, *, event_id: int, pk: int) -> bool:
        with self._transaction.atomic():
            self._time_slots.read_by_event(event_id, pk)
            if self._time_slots.has_proposals(pk):
                return False
            self._time_slots.delete(pk)
            return True
