from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum, auto
from typing import TYPE_CHECKING, Protocol, TypedDict

from pydantic import BaseModel, ConfigDict

from ludamus.pacts.crowd import UserDTO

if TYPE_CHECKING:
    from ludamus.pacts.images import UploadedFileProtocol


class EncountersPolicy(StrEnum):
    """Who may create encounters in a sphere. NONE turns the feature off."""

    NONE = "none"
    MANAGERS = "managers"
    EVERYONE = "everyone"


class EncounterDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    creation_time: datetime
    creator_id: int
    description: str
    end_time: datetime | None
    game: str
    is_public: bool = False
    max_participants: int
    pk: int
    place: str
    share_code: str
    sphere_id: int
    start_time: datetime
    title: str
    header_image_url: str = ""
    header_image_original_name: str = ""


class EncounterRSVPDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    creation_time: datetime
    encounter_id: int
    ip_address: str
    pk: int
    user_id: int


class EncounterData(TypedDict, total=False):
    creator_id: int
    description: str
    end_time: datetime | None
    game: str
    header_image: UploadedFileProtocol | str
    is_public: bool
    max_participants: int
    place: str
    share_code: str
    sphere_id: int
    start_time: datetime
    title: str


@dataclass
class EncounterIndexItem:
    encounter: EncounterDTO
    rsvp_count: int
    is_mine: bool
    organizer_name: str


@dataclass
class EncounterFeed:
    upcoming: list[EncounterIndexItem]
    past: list[EncounterIndexItem]


class EncounterRepositoryProtocol(Protocol):
    @staticmethod
    def create(data: EncounterData) -> EncounterDTO: ...
    @staticmethod
    def exists_for_sphere(sphere_id: int) -> bool: ...
    @staticmethod
    def read(pk: int, sphere_id: int) -> EncounterDTO: ...
    @staticmethod
    def read_by_share_code(share_code: str, sphere_id: int) -> EncounterDTO: ...
    @staticmethod
    def list_visible_upcoming(
        sphere_id: int, user_id: int | None
    ) -> list[EncounterDTO]: ...
    @staticmethod
    def list_visible_past(
        sphere_id: int, user_id: int | None, limit: int
    ) -> list[EncounterDTO]: ...
    @staticmethod
    def update(pk: int, data: EncounterData) -> None: ...
    @staticmethod
    def delete(pk: int) -> None: ...


class EncounterRSVPRepositoryProtocol(Protocol):
    @staticmethod
    def create(
        encounter_id: int, ip_address: str, user_id: int
    ) -> EncounterRSVPDTO: ...
    @staticmethod
    def list_by_encounter(encounter_id: int) -> list[EncounterRSVPDTO]: ...
    @staticmethod
    def count_by_encounter(encounter_id: int) -> int: ...
    @staticmethod
    def count_by_encounters(encounter_ids: list[int]) -> dict[int, int]: ...
    @staticmethod
    def recent_rsvp_exists(ip_address: str, seconds: int = 60) -> bool: ...
    @staticmethod
    def user_has_rsvpd(encounter_id: int, user_id: int) -> bool: ...
    @staticmethod
    def delete_by_user(encounter_id: int, user_id: int) -> None: ...


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
    def enabled(self, sphere_id: int) -> bool: ...
    def list_feed(self, *, sphere_id: int, user_id: int | None) -> EncounterFeed: ...
    def can_create(self, *, sphere_id: int, user_id: int) -> bool: ...
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
