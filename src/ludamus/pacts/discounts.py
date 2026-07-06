from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


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


class DiscountsServiceProtocol(Protocol):
    def list_by_event(self, event_pk: int) -> list[DiscountDTO]: ...
    def get(self, pk: int) -> DiscountDTO: ...
    def create(self, event_pk: int, data: DiscountData) -> DiscountDTO: ...
    def update(self, pk: int, data: DiscountData) -> DiscountDTO: ...
    def soft_delete(self, pk: int) -> None: ...


class SheetExportError(Exception):
    pass


class DiscountExportLabels(BaseModel):
    # Localized strings the export sheet is rendered with. Built at the gate
    # (where gettext lives) so the mill stays framework-free; maps are keyed
    # by the raw enum values stored on the DTOs.
    headers: list[str]
    accreditation_types: dict[str, str]
    kinds: dict[str, str]


class SheetWriterProtocol(Protocol):
    def write_rows(
        self, *, secret: bytes, spreadsheet_id: str, rows: list[list[str]]
    ) -> None: ...


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
