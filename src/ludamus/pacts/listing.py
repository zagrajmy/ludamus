"""Listings on the looking-for-group board: who is sought, to do what, when."""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, NotRequired, Protocol, TypedDict

from pydantic import BaseModel

if TYPE_CHECKING:
    from ludamus.pacts.images import UploadedFileProtocol

LISTING_TITLE_MAX_LENGTH = 255
LISTING_TEXT_MAX_LENGTH = 255


class ListingSeeking(StrEnum):
    PLAYERS = "players"
    GM = "gm"


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
    pk: int
    sphere_id: int
    author_id: int
    author_name: str
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


class ListingBoardRowDTO(BaseModel):
    pk: int
    status: ListingStatus
    title: str
    what: str
    tag_ids: list[int]


class BoardFiltersDict(TypedDict):
    seeking: ListingSeeking | None
    search: str
    tag_ids: list[int]
    show_closed: bool


class BoardTagFacetDTO(BaseModel):
    pk: int
    name: str
    count: int
    selected: bool
    children: list[BoardTagFacetDTO]


class BoardCategoryFacetDTO(BaseModel):
    slug: str
    name: str
    tags: list[BoardTagFacetDTO]


class BoardSearchDTO(BaseModel):
    listing_ids: list[int]
    facets: list[BoardCategoryFacetDTO]


class ListingWriteDict(TypedDict):
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
    header_image: NotRequired[UploadedFileProtocol | str]


class ListingCreateDict(ListingWriteDict):
    sphere_id: int
    author_id: int


class ListingContactMissingError(Exception):
    """The contact the listing names is not on the author's profile."""

    def __init__(self, contact: ListingContact) -> None:
        super().__init__(contact)
        self.contact = contact


class ListingStatusError(Exception):
    """The listing is not in the status the transition starts from."""


class ListingRepositoryProtocol(Protocol):
    @staticmethod
    def create(data: ListingCreateDict) -> int: ...
    @staticmethod
    def update(pk: int, data: ListingWriteDict) -> None: ...
    @staticmethod
    def set_tags(*, pk: int, tag_ids: list[int]) -> None: ...
    @staticmethod
    def read(*, pk: int, sphere_id: int) -> ListingDTO: ...
    @staticmethod
    def read_authored(*, pk: int, sphere_id: int, author_id: int) -> ListingDTO: ...
    @staticmethod
    def lock_authored(*, pk: int, sphere_id: int, author_id: int) -> ListingDTO: ...
    @staticmethod
    def board_rows(
        *, sphere_id: int, seeking: ListingSeeking | None, statuses: list[ListingStatus]
    ) -> list[ListingBoardRowDTO]: ...
    @staticmethod
    def read_many(pks: list[int]) -> list[ListingDTO]: ...
    @staticmethod
    def list_authored(*, sphere_id: int, author_id: int) -> list[ListingDTO]: ...
    @staticmethod
    def open(*, pk: int, at: datetime) -> None: ...
    @staticmethod
    def close(pk: int) -> None: ...
    @staticmethod
    def close_opened_before(cutoff: datetime) -> int: ...


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
    def search_board(
        self, *, sphere_id: int, filters: BoardFiltersDict
    ) -> BoardSearchDTO: ...
    def read_many(self, pks: list[int]) -> list[ListingDTO]: ...
    def contact_channels(self, user_id: int) -> list[ListingContact]: ...
    def authored(self, *, sphere_id: int, author_id: int) -> list[ListingDTO]: ...
    def publish(
        self, *, pk: int, sphere_id: int, author_id: int, now: datetime
    ) -> None: ...
    def close(self, *, pk: int, sphere_id: int, author_id: int) -> None: ...
    def reopen(
        self, *, pk: int, sphere_id: int, author_id: int, now: datetime
    ) -> None: ...
    def close_stale(self, now: datetime) -> int: ...
    @staticmethod
    def open_for_days() -> int: ...
