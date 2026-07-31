from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel

from ludamus.pacts.legacy import EventDTO, PanelStatsDTO, TimeSlotDTO

if TYPE_CHECKING:
    from datetime import datetime


class TimeSlotValidationError(StrEnum):
    START_NOT_BEFORE_END = "start_not_before_end"
    OUTSIDE_EVENT_DATES = "outside_event_dates"
    OVERLAPS_EXISTING_SLOT = "overlaps_existing_slot"


class EventPanelContextDTO(BaseModel):
    events: list[EventDTO]
    current_event: EventDTO
    is_proposal_active: bool
    stats: PanelStatsDTO


class EventPanelServiceProtocol(Protocol):
    def load_context(self, sphere_id: int, slug: str) -> EventPanelContextDTO: ...


class PanelTimeSlotsServiceProtocol(Protocol):
    def list_for_event(self, event_id: int) -> list[TimeSlotDTO]: ...
    def read(self, *, event_id: int, pk: int) -> TimeSlotDTO: ...
    def create(
        self, *, event: EventDTO, start_time: datetime, end_time: datetime
    ) -> list[TimeSlotValidationError]: ...
    def update(
        self, *, event: EventDTO, pk: int, start_time: datetime, end_time: datetime
    ) -> list[TimeSlotValidationError]: ...
    def delete(self, *, event_id: int, pk: int) -> bool: ...
