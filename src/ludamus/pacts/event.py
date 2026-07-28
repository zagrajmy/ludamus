from typing import Protocol

from pydantic import BaseModel

from ludamus.pacts.legacy import EventDTO, PanelStatsDTO


class EventPanelContextDTO(BaseModel):
    events: list[EventDTO]
    current_event: EventDTO
    is_proposal_active: bool
    stats: PanelStatsDTO


class EventPanelServiceProtocol(Protocol):
    def load_context(self, sphere_id: int, slug: str) -> EventPanelContextDTO: ...
