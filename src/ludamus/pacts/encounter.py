from enum import StrEnum, auto
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from ludamus.pacts.crowd import UserDTO
from ludamus.pacts.legacy import (
    EncounterData,
    EncounterDTO,
    EncounterIndexItem,
    EncounterIndexResult,
)


class EncounterDetailContextDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    encounter: EncounterDTO
    creator: UserDTO
    attendees: list[UserDTO]
    rsvp_count: int
    is_creator: bool
    user_has_rsvpd: bool

    # Derived from the capacity and the signup count rather than stored, so
    # the two can't drift apart.
    @property
    def spots_remaining(self) -> int | None:
        limit = self.encounter.max_participants
        return max(0, limit - self.rsvp_count) if limit > 0 else None

    @property
    def is_full(self) -> bool:
        return self.spots_remaining == 0


class RSVPOutcome(StrEnum):
    CREATED = auto()
    FULL = auto()
    THROTTLED = auto()
    ALREADY_SIGNED_UP = auto()


class EncounterServiceProtocol(Protocol):
    def build_index(self, *, sphere_id: int, user_id: int) -> EncounterIndexResult: ...
    def list_public_upcoming(self, *, sphere_id: int) -> list[EncounterIndexItem]: ...
    def can_set_public(self, *, sphere_id: int, user_id: int) -> bool: ...
    def build_detail(
        self, *, share_code: str, sphere_id: int, current_user_id: int | None
    ) -> EncounterDetailContextDTO: ...
    def read_by_share_code(
        self, *, share_code: str, sphere_id: int
    ) -> EncounterDTO: ...
    def create(self, data: EncounterData) -> EncounterDTO: ...
    def read_owned(self, *, pk: int, sphere_id: int, user_id: int) -> EncounterDTO: ...
    def update_owned(
        self, *, pk: int, sphere_id: int, user_id: int, data: EncounterData
    ) -> EncounterDTO: ...
    def delete_owned(self, *, pk: int, sphere_id: int, user_id: int) -> None: ...
    def rsvp(
        self, *, share_code: str, sphere_id: int, user_id: int, ip_address: str
    ) -> RSVPOutcome: ...
    def cancel_rsvp(self, *, share_code: str, sphere_id: int, user_id: int) -> None: ...
