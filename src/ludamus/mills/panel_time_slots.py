from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.mills.legacy import PanelService
from ludamus.pacts.event import PanelTimeSlotsServiceProtocol

if TYPE_CHECKING:
    from datetime import datetime

    from ludamus.pacts.legacy import EventDTO, TimeSlotDTO, TimeSlotRepositoryProtocol
    from ludamus.pacts.services import TransactionProtocol


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
    ) -> list[str]:
        with self._transaction.atomic():
            existing = self._time_slots.list_by_event(event.pk)
            errors = PanelService.validate_time_slot(
                start_time, end_time, event, existing
            )
            if not errors:
                self._time_slots.create(event.pk, start_time, end_time)
            return errors

    def update(
        self, *, event: EventDTO, pk: int, start_time: datetime, end_time: datetime
    ) -> list[str]:
        with self._transaction.atomic():
            # Scope the pk to the panel's event before writing; a foreign pk
            # raises NotFoundError with no side effects.
            self._time_slots.read_by_event(event.pk, pk)
            existing = [
                slot
                for slot in self._time_slots.list_by_event(event.pk)
                if slot.pk != pk
            ]
            errors = PanelService.validate_time_slot(
                start_time, end_time, event, existing
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
