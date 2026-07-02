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
