from enum import StrEnum, auto
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from ludamus.pacts.crowd import UserDTO
from ludamus.pacts.legacy import EncounterData, EncounterDTO, EncounterIndexResult


class EncounterDetailContextDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    encounter: EncounterDTO
    creator: UserDTO
    attendees: list[UserDTO]
    rsvp_count: int
    is_full: bool
    spots_remaining: int | None
    is_creator: bool
    user_has_rsvpd: bool


class RSVPOutcome(StrEnum):
    CREATED = auto()
    FULL = auto()
    THROTTLED = auto()
    ALREADY_SIGNED_UP = auto()


class EncounterServiceProtocol(Protocol):
    def build_index(self, *, sphere_id: int, user_id: int) -> EncounterIndexResult: ...
    def build_detail(
        self, *, share_code: str, current_user_id: int | None
    ) -> EncounterDetailContextDTO: ...
    def read_by_share_code(self, share_code: str) -> EncounterDTO: ...
    def create(self, data: EncounterData) -> EncounterDTO: ...
    def read_owned(self, *, pk: int, user_id: int) -> EncounterDTO: ...
    def update_owned(self, *, pk: int, user_id: int, data: EncounterData) -> None: ...
    def delete_owned(self, *, pk: int, user_id: int) -> None: ...
    def rsvp(
        self, *, share_code: str, user_id: int, ip_address: str
    ) -> RSVPOutcome: ...
    def cancel_rsvp(self, *, share_code: str, user_id: int) -> None: ...
