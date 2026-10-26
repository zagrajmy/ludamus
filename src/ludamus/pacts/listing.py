"""Listings on the looking-for-group board: who is sought, to do what, when."""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, NotRequired, Protocol, TypedDict

from pydantic import BaseModel

if TYPE_CHECKING:
    from ludamus.pacts.images import UploadedFileProtocol

LISTING_TITLE_MAX_LENGTH = 255
LISTING_TEXT_MAX_LENGTH = 255
LISTING_MESSAGE_MAX_LENGTH = 1000


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


class ListingResponseStatus(StrEnum):
    WAITING = "waiting"
    DECLINED = "declined"
    NOT_CHOSEN = "not_chosen"


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
    expanded: bool
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


class ListingResponseDTO(BaseModel):
    pk: int
    listing_id: int
    user_id: int
    user_name: str
    message: str
    status: ListingResponseStatus
    decline_message: str
    creation_time: datetime


class ListingResponseCreateDict(TypedDict):
    listing_id: int
    user_id: int
    message: str
    contact: ListingContact


class ListingNotification(BaseModel):
    recipient_user_id: int
    listing_id: int
    listing_title: str
    responder_name: str = ""
    message: str = ""


class ListingContactMissingError(Exception):
    """The contact the listing names is not on the author's profile."""

    def __init__(self, contact: ListingContact) -> None:
        super().__init__(contact)
        self.contact = contact


class ListingStatusError(Exception):
    """The listing is not in the status the transition starts from."""


class ListingResponseError(Exception):
    """The response cannot be sent or changed in its current state."""


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
    def lock(*, pk: int, sphere_id: int) -> ListingDTO: ...
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
    def close_opened_before(cutoff: datetime) -> list[int]: ...


class ListingResponseRepositoryProtocol(Protocol):
    @staticmethod
    def create(data: ListingResponseCreateDict) -> int: ...
    @staticmethod
    def read(*, pk: int, listing_id: int) -> ListingResponseDTO: ...
    @staticmethod
    def read_own(*, listing_id: int, user_id: int) -> ListingResponseDTO | None: ...
    @staticmethod
    def list_for_listing(
        *, listing_id: int, status: ListingResponseStatus
    ) -> list[ListingResponseDTO]: ...
    @staticmethod
    def count_by_status(listing_id: int) -> dict[ListingResponseStatus, int]: ...
    @staticmethod
    def waiting_user_ids(listing_id: int) -> list[int]: ...
    @staticmethod
    def decline(*, pk: int, message: str) -> None: ...
    @staticmethod
    def mark_not_chosen(listing_id: int) -> None: ...
    @staticmethod
    def delete(pk: int) -> None: ...


class ListingNotifierProtocol(Protocol):
    def notify_listing_interested(self, notification: ListingNotification) -> None: ...
    def notify_listing_declined(self, notification: ListingNotification) -> None: ...
    def notify_listing_not_chosen(self, notification: ListingNotification) -> None: ...
    def notify_listing_changed(self, notification: ListingNotification) -> None: ...


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
    def respond(
        self,
        *,
        pk: int,
        sphere_id: int,
        user_id: int,
        message: str,
        contact: ListingContact,
    ) -> None: ...
    def withdraw(self, *, pk: int, sphere_id: int, user_id: int) -> None: ...
    def decline(
        self, *, pk: int, sphere_id: int, author_id: int, response_id: int, message: str
    ) -> None: ...
    def own_response(self, *, pk: int, user_id: int) -> ListingResponseDTO | None: ...
    def responses(
        self, *, pk: int, sphere_id: int, author_id: int, status: ListingResponseStatus
    ) -> list[ListingResponseDTO]: ...
    def response_counts(self, pk: int) -> dict[ListingResponseStatus, int]: ...
    @staticmethod
    def open_for_days() -> int: ...
