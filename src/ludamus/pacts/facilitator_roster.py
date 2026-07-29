from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ludamus.pacts.legacy import FacilitatorDTO, FacilitatorListItemDTO


class FacilitatorRosterRepositoryProtocol(Protocol):
    @staticmethod
    def read(pk: int) -> FacilitatorDTO: ...
    @staticmethod
    def list_by_event(event_id: int) -> list[FacilitatorListItemDTO]: ...


class FacilitatorRosterServiceProtocol(Protocol):
    def list_by_event(self, event_pk: int) -> list[FacilitatorListItemDTO]: ...
    def read_scoped(self, *, event_pk: int, facilitator_id: int) -> FacilitatorDTO: ...
