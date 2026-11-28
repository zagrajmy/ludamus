"""The board: a Little Table room in a frame, with the sphere's own chat."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from ludamus.pacts.ids import UserId

BOARD_TITLE_MAX_LENGTH = 80
BOARD_ROOM_CODE_MAX_LENGTH = 64


class BoardDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pk: int
    sphere_id: int
    creator_id: int
    title: str
    share_code: str
    # The room's code on Little Table: its link is <origin>/b/<room_code>.
    room_code: str
    creation_time: datetime


class BoardPageDTO(BaseModel):
    """A board as its page shows it: the frame, and the chat beside it."""

    pk: int
    title: str
    share_code: str
    room_url: str
    # The origin the frame loads from, for the page's frame-src.
    room_origin: str
    is_owner: bool
    # The board's chat, once there is one and this person is in it.
    chat_id: int | None


class BoardListItemDTO(BaseModel):
    pk: int
    title: str
    share_code: str
    is_owner: bool
    # When this person last opened it, or else when it was created.
    last_opened_at: datetime


class BoardTitleInvalidError(Exception):
    """The title is empty or too long."""


class BoardRoomLinkInvalidError(Exception):
    """The link is not a Little Table room on the configured origin."""


class BoardRepositoryProtocol(Protocol):
    @staticmethod
    def create(
        *,
        sphere_id: int,
        creator_id: UserId,
        title: str,
        share_code: str,
        room_code: str,
    ) -> BoardDTO: ...
    @staticmethod
    def read_by_share_code(*, share_code: str, sphere_id: int) -> BoardDTO: ...
    @staticmethod
    def read_owned(*, pk: int, sphere_id: int, creator_id: UserId) -> BoardDTO: ...
    @staticmethod
    def update(*, pk: int, title: str, room_code: str) -> None: ...
    @staticmethod
    def delete(pk: int) -> None: ...

    # Whether this was the person's first visit.
    @staticmethod
    def record_visit(*, pk: int, user_id: UserId, now: datetime) -> bool: ...
    @staticmethod
    def list_for(*, sphere_id: int, user_id: UserId) -> list[BoardListItemDTO]: ...


class BoardServiceProtocol(Protocol):
    def available(self) -> bool: ...
    def room_url(self, room_code: str) -> str: ...
    def create(
        self, *, sphere_id: int, user_id: UserId, title: str, room_link: str
    ) -> BoardDTO: ...
    def open(
        self, *, share_code: str, sphere_id: int, user_id: UserId | None, now: datetime
    ) -> BoardPageDTO: ...
    def read_owned(self, *, pk: int, sphere_id: int, user_id: UserId) -> BoardDTO: ...
    def update(
        self, *, pk: int, sphere_id: int, user_id: UserId, title: str, room_link: str
    ) -> BoardDTO: ...
    def delete(self, *, pk: int, sphere_id: int, user_id: UserId) -> None: ...
    def list_mine(
        self, *, sphere_id: int, user_id: UserId
    ) -> list[BoardListItemDTO]: ...
