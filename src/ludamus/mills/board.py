"""Boards: Little Table rooms a sphere keeps a list of, each with its chat."""

from __future__ import annotations

import logging
import string
from secrets import choice
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from ludamus.pacts.board import (
    BOARD_TITLE_MAX_LENGTH,
    BoardPageDTO,
    BoardRoomLinkInvalidError,
    BoardServiceProtocol,
    BoardTitleInvalidError,
)
from ludamus.pacts.errors import NotFoundError
from ludamus.specs.board import BOARD_ROOM_PATH, BOARD_SHARE_CODE_LENGTH

if TYPE_CHECKING:
    from datetime import datetime

    from ludamus.pacts.board import BoardDTO, BoardListItemDTO, BoardRepositoryProtocol
    from ludamus.pacts.ids import UserId
    from ludamus.pacts.parley import ParleyOwnedChatProtocol
    from ludamus.pacts.services import TransactionProtocol

logger = logging.getLogger(__name__)

_SHARE_CODE_ALPHABET = string.ascii_letters + string.digits


def _new_share_code() -> str:
    return "".join(choice(_SHARE_CODE_ALPHABET) for _ in range(BOARD_SHARE_CODE_LENGTH))


def _clean_title(title: str) -> str:
    cleaned = " ".join(title.split())
    if not cleaned or len(cleaned) > BOARD_TITLE_MAX_LENGTH:
        raise BoardTitleInvalidError
    return cleaned


def room_code_of(*, link: str, origin: str) -> str:
    """Read a Little Table room's code from the link its page gives.

    Only rooms on `origin` count: the frame and the page's frame-src name
    that origin alone, so a link elsewhere would open a frame that never loads.

    Raises:
        BoardRoomLinkInvalidError: the link is not <origin>/b/<code>.

    Returns:
        The room's code.
    """
    try:
        address = urlsplit(link.strip())
    except ValueError as error:
        raise BoardRoomLinkInvalidError from error
    expected = urlsplit(origin)
    same_origin = (address.scheme, address.netloc.lower()) == (
        expected.scheme,
        expected.netloc.lower(),
    )
    if not same_origin or not (match := BOARD_ROOM_PATH.fullmatch(address.path)):
        raise BoardRoomLinkInvalidError
    return match["code"]


class BoardService(BoardServiceProtocol):
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        boards: BoardRepositoryProtocol,
        chats: ParleyOwnedChatProtocol,
        little_table_url: str,
    ) -> None:
        self._transaction = transaction
        self._boards = boards
        self._chats = chats
        self._origin = little_table_url

    def available(self) -> bool:
        return bool(self._origin)

    def _require_available(self) -> str:
        if not self._origin:
            raise NotFoundError
        return self._origin

    def room_url(self, room_code: str) -> str:
        return f"{self._require_available()}/b/{room_code}"

    def create(
        self, *, sphere_id: int, user_id: UserId, title: str, room_link: str
    ) -> BoardDTO:
        """Keep a Little Table room on this sphere's list, and open its chat.

        Raises:
            BoardTitleInvalidError: the title is empty or too long.
            BoardRoomLinkInvalidError: the link is not a Little Table room.

        Returns:
            The new board.
        """
        origin = self._require_available()
        cleaned = _clean_title(title)
        room_code = room_code_of(link=room_link, origin=origin)
        board = self._boards.create(
            sphere_id=sphere_id,
            creator_id=user_id,
            title=cleaned,
            share_code=_new_share_code(),
            room_code=room_code,
        )
        self._chats.sync(board.pk)
        logger.info(
            "Board created",
            extra={"board_id": board.pk, "sphere_id": sphere_id, "user_id": user_id},
        )
        return board

    def open(
        self, *, share_code: str, sphere_id: int, user_id: UserId | None, now: datetime
    ) -> BoardPageDTO:
        """Find a board of this sphere by its link, for whoever holds it.

        The link is the capability, as with an encounter's. A signed-in
        person who opens it gets the board on their list and joins its chat.

        Returns:
            The board's frame and, for a signed-in person, its chat.
        """
        origin = self._require_available()
        board = self._boards.read_by_share_code(
            share_code=share_code, sphere_id=sphere_id
        )
        chat_id = None
        if user_id is not None:
            first_visit = self._boards.record_visit(
                pk=board.pk, user_id=user_id, now=now
            )
            chat_id = self._chats.chat_id(board.pk)
            if first_visit or chat_id is None:
                self._chats.sync(board.pk)
                chat_id = self._chats.chat_id(board.pk)
            if first_visit:
                logger.info(
                    "Board joined", extra={"board_id": board.pk, "user_id": user_id}
                )
        return BoardPageDTO(
            pk=board.pk,
            title=board.title,
            share_code=board.share_code,
            room_url=f"{origin}/b/{board.room_code}",
            room_origin=origin,
            is_owner=board.creator_id == user_id,
            chat_id=chat_id,
        )

    def read_owned(self, *, pk: int, sphere_id: int, user_id: UserId) -> BoardDTO:
        self._require_available()
        return self._boards.read_owned(pk=pk, sphere_id=sphere_id, creator_id=user_id)

    def update(
        self, *, pk: int, sphere_id: int, user_id: UserId, title: str, room_link: str
    ) -> BoardDTO:
        """Rename the board or point it at another Little Table room.

        Raises:
            BoardTitleInvalidError: the title is empty or too long.
            BoardRoomLinkInvalidError: the link is not a Little Table room.

        Returns:
            The board as saved.
        """
        origin = self._require_available()
        cleaned = _clean_title(title)
        room_code = room_code_of(link=room_link, origin=origin)
        with self._transaction.atomic():
            board = self.read_owned(pk=pk, sphere_id=sphere_id, user_id=user_id)
            self._boards.update(pk=board.pk, title=cleaned, room_code=room_code)
            updated = self.read_owned(pk=pk, sphere_id=sphere_id, user_id=user_id)
        logger.info(
            "Board updated",
            extra={
                "board_id": pk,
                "user_id": user_id,
                "room_changed": board.room_code != room_code,
            },
        )
        return updated

    def delete(self, *, pk: int, sphere_id: int, user_id: UserId) -> None:
        """Take the board off every list and empty its chat.

        The chat's record stays, with any reports made in it, as an
        encounter's does. The Little Table room is Little Table's: whoever
        has its link still reaches it there.
        """
        with self._transaction.atomic():
            board = self.read_owned(pk=pk, sphere_id=sphere_id, user_id=user_id)
            self._boards.delete(board.pk)
        self._chats.sync(board.pk)
        logger.info(
            "Board deleted",
            extra={"board_id": board.pk, "sphere_id": sphere_id, "user_id": user_id},
        )

    def list_mine(self, *, sphere_id: int, user_id: UserId) -> list[BoardListItemDTO]:
        if not self.available():
            return []
        return self._boards.list_for(sphere_id=sphere_id, user_id=user_id)
