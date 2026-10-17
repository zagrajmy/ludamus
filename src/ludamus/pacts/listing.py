"""Listings on the looking-for-group board: who seeks whom, to do what, when."""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, TypedDict

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from ludamus.pacts.images import UploadedFileProtocol

LISTING_TITLE_MAX_LENGTH = 255
LISTING_TEXT_MAX_LENGTH = 255


class ListingRole(StrEnum):
    GM = "gm"
    PLAYER = "player"
    GROUP = "group"


class ListingSeeking(StrEnum):
    PLAYERS = "players"
    GM = "gm"
    GROUP = "group"


# The only who-seeks-whom pairs a listing may take; the column check holds the
# same set.
LISTING_PAIRS = (
    (ListingRole.GM, ListingSeeking.PLAYERS),
    (ListingRole.PLAYER, ListingSeeking.GM),
    (ListingRole.PLAYER, ListingSeeking.GROUP),
    (ListingRole.GROUP, ListingSeeking.PLAYERS),
    (ListingRole.GROUP, ListingSeeking.GM),
)


class ListingStatus(StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    CLOSED = "closed"


class ListingContact(StrEnum):
    DISCORD = "discord"
    EMAIL = "email"


class ListingTagDTO(BaseModel):
    pk: int
    name: str


class ListingDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pk: int
    sphere_id: int
    author_id: int
    author_name: str
    role: ListingRole
    seeking: ListingSeeking
    title: str
    what: str
    description: str
    tags: list[ListingTagDTO]
    seats: int | None
    medium: str
    place: str
    starts_at: datetime | None
    when_text: str
    contact: ListingContact
    status: ListingStatus
    opened_at: datetime | None
    header_image_url: str
    header_image_original_name: str


class ListingWriteDict(TypedDict, total=False):
    role: ListingRole
    seeking: ListingSeeking
    title: str
    what: str
    description: str
    seats: int | None
    medium: str
    place: str
    starts_at: datetime | None
    when_text: str
    contact: ListingContact
    header_image: UploadedFileProtocol | str


class ListingCreateDict(ListingWriteDict):
    sphere_id: int
    author_id: int


class ListingContactMissingError(Exception):
    """The contact the listing names is not on the author's profile."""


class ListingRepositoryProtocol(Protocol):
    @staticmethod
    def create(data: ListingCreateDict) -> int: ...
    @staticmethod
    def update(pk: int, data: ListingWriteDict) -> None: ...
    @staticmethod
    def set_tags(*, pk: int, picked: list[int], with_ancestors: list[int]) -> None: ...
    @staticmethod
    def read(*, pk: int, sphere_id: int) -> ListingDTO: ...
    @staticmethod
    def read_authored(*, pk: int, sphere_id: int, author_id: int) -> ListingDTO: ...
    @staticmethod
    def list_open(sphere_id: int) -> list[ListingDTO]: ...
    @staticmethod
    def list_authored(*, sphere_id: int, author_id: int) -> list[ListingDTO]: ...
    @staticmethod
    def set_status(
        *, pk: int, status: ListingStatus, opened_at: datetime | None = None
    ) -> None: ...
    @staticmethod
    def close_opened_before(cutoff: datetime) -> int: ...
    @staticmethod
    def discord_of(user_id: int) -> str: ...


class ListingServiceProtocol(Protocol):
    def create(
        self,
        data: ListingCreateDict,
        *,
        tag_ids: list[int],
        publish_at: datetime | None,
    ) -> int: ...
    def update(
        self,
        *,
        pk: int,
        sphere_id: int,
        author_id: int,
        data: ListingWriteDict,
        tag_ids: list[int],
    ) -> None: ...
    def read_visible(
        self, *, pk: int, sphere_id: int, viewer_id: int | None
    ) -> ListingDTO: ...
    def read_authored(
        self, *, pk: int, sphere_id: int, author_id: int
    ) -> ListingDTO: ...
    def board(self, sphere_id: int) -> list[ListingDTO]: ...
    def has_discord(self, user_id: int) -> bool: ...
    def authored(self, *, sphere_id: int, author_id: int) -> list[ListingDTO]: ...
    def publish(
        self, *, pk: int, sphere_id: int, author_id: int, now: datetime
    ) -> None: ...
    def close(self, *, pk: int, sphere_id: int, author_id: int) -> None: ...
    def reopen(
        self, *, pk: int, sphere_id: int, author_id: int, now: datetime
    ) -> None: ...
    def close_stale(self, now: datetime) -> int: ...
