from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.pacts import NotFoundError
from ludamus.pacts.facilitator_roster import FacilitatorRosterServiceProtocol

if TYPE_CHECKING:
    from ludamus.pacts.facilitator_roster import FacilitatorRosterRepositoryProtocol
    from ludamus.pacts.legacy import FacilitatorDTO, FacilitatorListItemDTO


class FacilitatorRosterService(FacilitatorRosterServiceProtocol):
    def __init__(self, facilitators: FacilitatorRosterRepositoryProtocol) -> None:
        self._facilitators = facilitators

    def list_by_event(self, event_pk: int) -> list[FacilitatorListItemDTO]:
        return self._facilitators.list_by_event(event_pk)

    def read_scoped(self, *, event_pk: int, facilitator_id: int) -> FacilitatorDTO:
        facilitator = self._facilitators.read(facilitator_id)
        if facilitator.event_id != event_pk:
            raise NotFoundError
        return facilitator
