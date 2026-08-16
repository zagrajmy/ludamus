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
    from_rules: bool
    creation_time: datetime
    modification_time: datetime


class DiscountData(BaseModel):
    facilitator_id: int
    kind: DiscountKind
    value: Decimal = Field(gt=0)
    note: str = Field(default="", max_length=255)
    from_rules: bool = False


class DiscountMethod(StrEnum):
    # What the rule measures on a facilitator's scheduled program.
    STARTED_HOURS = "started_hours"
    SESSION_COUNT = "session_count"


class DiscountRuleData(BaseModel):
    method: DiscountMethod
    quantity: int = Field(gt=0)
    percent: Decimal = Field(gt=0, le=100)
    order: int = Field(ge=0)


class DiscountRuleDTO(DiscountRuleData):
    model_config = ConfigDict(from_attributes=True)

    pk: int
    event_id: int


class DiscountRuleRepositoryProtocol(Protocol):
    @staticmethod
    def list_for_event(event_id: int) -> list[DiscountRuleDTO]: ...
    @staticmethod
    def read(event_id: int, pk: int) -> DiscountRuleDTO | None: ...
    @staticmethod
    def create(event_id: int, data: DiscountRuleData) -> DiscountRuleDTO: ...
    @staticmethod
    def update(
        *, event_id: int, pk: int, data: DiscountRuleData
    ) -> DiscountRuleDTO | None: ...
    @staticmethod
    def delete(event_id: int, pk: int) -> bool: ...


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


class FacilitatorScheduleRow(BaseModel):
    facilitator_id: int
    session_count: int
    minutes: int


class ScheduledProgramRepositoryProtocol(Protocol):
    @staticmethod
    def list_facilitator_schedule(event_pk: int) -> list[FacilitatorScheduleRow]: ...


class AccreditationWriterProtocol(Protocol):
    def set_accreditation(
        self,
        *,
        event_id: int,
        facilitator_slug: str,
        accreditation_type: str,
        user_id: int | None = None,
    ) -> None: ...


class DiscountSyncResultDTO(BaseModel):
    marked: int
    unmarked: int
    discounts_set: int
    discounts_cleared: int


class DiscountRosterEntryDTO(BaseModel):
    facilitator: FacilitatorListItemDTO
    discount: DiscountDTO | None


class DiscountsServiceProtocol(Protocol):
    def list_roster(self, event_pk: int) -> list[DiscountRosterEntryDTO]: ...
    def list_rules(self, event_pk: int) -> list[DiscountRuleDTO]: ...
    def read_rule(self, event_pk: int, pk: int) -> DiscountRuleDTO | None: ...
    def create_rule(self, event_pk: int, data: DiscountRuleData) -> DiscountRuleDTO: ...
    def update_rule(
        self, *, event_pk: int, pk: int, data: DiscountRuleData
    ) -> DiscountRuleDTO | None: ...
    def delete_rule(self, event_pk: int, pk: int) -> bool: ...
    def apply_from_agenda(
        self, *, event_pk: int, user_id: int | None = None
    ) -> DiscountSyncResultDTO: ...
    def read_scoped(self, *, event_pk: int, pk: int) -> DiscountDTO: ...
    def read_scoped_facilitator(
        self, *, event_pk: int, facilitator_id: int
    ) -> FacilitatorDTO: ...
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
        self,
        *,
        secret: bytes,
        spreadsheet_id: str,
        tab_title: str,
        rows: list[list[str]],
    ) -> None: ...


class DiscountsExportServiceProtocol(Protocol):
    def export_to_sheet(
        self,
        *,
        sphere_id: int,
        event_pk: int,
        connection_id: int,
        spreadsheet_id: str,
        tab_title: str,
        labels: DiscountExportLabels,
    ) -> int: ...
