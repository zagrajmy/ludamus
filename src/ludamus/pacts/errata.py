"""Post-publication agenda changes — the ones somebody has to announce."""

from datetime import datetime
from enum import StrEnum, auto
from typing import Protocol

from pydantic import BaseModel


class ErratumKind(StrEnum):
    ADDED = auto()
    MOVED = auto()
    REMOVED = auto()


class ErratumDTO(BaseModel):
    # A move spans the two log rows it was written as, so an erratum names
    # every row behind it rather than a single pk.
    log_pks: list[int]
    kind: ErratumKind
    session_id: int
    session_title: str
    user_name: str
    creation_time: datetime
    old_space_name: str | None
    old_start_time: datetime | None
    new_space_name: str | None
    new_start_time: datetime | None
    is_acknowledged: bool
    acknowledged_by_name: str


class ErrataServiceProtocol(Protocol):
    def list_for_event(self, event_pk: int) -> list[ErratumDTO]: ...
    def set_acknowledged(
        self, *, event_pk: int, log_pks: list[int], user_id: int, acknowledged: bool
    ) -> None: ...
