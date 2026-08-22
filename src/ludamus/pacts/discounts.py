from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict, Field

from ludamus.pacts.event import FacilitatorListItemDTO

if TYPE_CHECKING:
    from ludamus.pacts.legacy import FacilitatorDTO


class DiscountKind(StrEnum):
    PERCENT = "percent"
    AMOUNT = "amount"


class DiscountDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pk: int
    event_id: int
    facilitator_id: int
    kind: DiscountKind
    value: Decimal
    note: str
    creation_time: datetime
    modification_time: datetime


class DiscountData(BaseModel):
    facilitator_id: int
    kind: DiscountKind
    value: Decimal = Field(gt=0)
    note: str = Field(default="", max_length=255)


class DiscountRepositoryProtocol(Protocol):
    @staticmethod
    def list_by_event(event_pk: int) -> list[DiscountDTO]: ...
    @staticmethod
    def get(pk: int) -> DiscountDTO: ...
    @staticmethod
    def create(event_pk: int, data: DiscountData) -> DiscountDTO: ...
    @staticmethod
    def update(pk: int, data: DiscountData) -> DiscountDTO: ...
    @staticmethod
    def soft_delete(pk: int) -> None: ...


class DiscountRosterEntryDTO(BaseModel):
    facilitator: FacilitatorListItemDTO
    discount: DiscountDTO | None


class DiscountsServiceProtocol(Protocol):
    def list_roster(self, event_pk: int) -> list[DiscountRosterEntryDTO]: ...
    def read_scoped(self, *, event_pk: int, pk: int) -> DiscountDTO: ...
    def read_scoped_facilitator(
        self, *, event_pk: int, facilitator_id: int
    ) -> FacilitatorDTO: ...
    def create(self, event_pk: int, data: DiscountData) -> DiscountDTO: ...
    def update(self, pk: int, data: DiscountData) -> DiscountDTO: ...
    def soft_delete(self, pk: int) -> None: ...


class DiscountExportLabels(BaseModel):
    # Localized strings the export sheet is rendered with. Built at the gate
    # (where gettext lives) so the mill stays framework-free; maps are keyed
    # by the raw enum values stored on the DTOs.
    headers: list[str]
    accreditation_types: dict[str, str]
    kinds: dict[str, str]


class DiscountsExportServiceProtocol(Protocol):
    def export_to_sheet(
        self,
        *,
        sphere_id: int,
        event_pk: int,
        connection_id: int,
        spreadsheet_id: str,
        labels: DiscountExportLabels,
    ) -> int: ...
