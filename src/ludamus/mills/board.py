"""Boards: who may open one, and the pass that lets them onto it."""

from __future__ import annotations

import logging
import string
import unicodedata
from hashlib import sha256
from secrets import choice, token_urlsafe
from typing import TYPE_CHECKING

from ludamus.pacts.board import (
    BOARD_TITLE_MAX_LENGTH,
    BoardBootstrapDTO,
    BoardNameInvalidError,
    BoardNameRequiredError,
    BoardPassClaims,
    BoardPersonDTO,
    BoardServiceProtocol,
    BoardThrottledError,
    BoardTitleInvalidError,
)
from ludamus.pacts.errors import NotFoundError
from ludamus.specs.board import (
    BOARD_BOOTSTRAP_LIMIT,
    BOARD_BOOTSTRAP_WINDOW_SECONDS,
    BOARD_NAME_MAX_LENGTH,
    BOARD_PASS_LIFETIME,
    BOARD_SHARE_CODE_LENGTH,
)

if TYPE_CHECKING:
    from datetime import datetime

    from ludamus.pacts.board import (
        BoardDTO,
        BoardGuestDTO,
        BoardListItemDTO,
        BoardRepositoryProtocol,
        BoardSignerProtocol,
        BoardWorkerDTO,
    )
    from ludamus.pacts.cache import CacheProtocol
    from ludamus.pacts.ids import UserId
    from ludamus.pacts.services import TransactionProtocol

logger = logging.getLogger(__name__)

_SHARE_CODE_ALPHABET = string.ascii_letters + string.digits
_MEMBER = "u:"
_GUEST = "g:"


def _new_share_code() -> str:
    return "".join(choice(_SHARE_CODE_ALPHABET) for _ in range(BOARD_SHARE_CODE_LENGTH))


def _printable(text: str) -> bool:
    return not any(unicodedata.category(char).startswith("C") for char in text)


def _clean_title(title: str) -> str:
    cleaned = " ".join(title.split())
    if not cleaned or len(cleaned) > BOARD_TITLE_MAX_LENGTH:
        raise BoardTitleInvalidError
    return cleaned


def clean_display_name(name: str) -> str:
    """Return the name as the board shows it.

    Raises:
        BoardNameInvalidError: when nothing printable is left, or too much.
    """
    cleaned = " ".join(name.split())
    if not cleaned or len(cleaned) > BOARD_NAME_MAX_LENGTH or not _printable(cleaned):
        raise BoardNameInvalidError
    return cleaned


class BoardService(BoardServiceProtocol):
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        boards: BoardRepositoryProtocol,
        signer: BoardSignerProtocol,
        cache: CacheProtocol,
        worker: BoardWorkerDTO | None,
    ) -> None:
        self._transaction = transaction
        self._boards = boards
        self._signer = signer
        self._cache = cache
        self._worker = worker

    def available(self) -> bool:
        return self._worker is not None

    def _require_available(self) -> BoardWorkerDTO:
        if self._worker is None:
            raise NotFoundError
        return self._worker

    def create(self, *, sphere_id: int, user_id: UserId, title: str) -> BoardDTO:
        self._require_available()
        board = self._boards.create(
            sphere_id=sphere_id,
            creator_id=user_id,
            title=_clean_title(title),
            share_code=_new_share_code(),
        )
        logger.info(
            "Board created",
            extra={"board_id": board.pk, "sphere_id": sphere_id, "user_id": user_id},
        )
        return board

    def open(
        self, *, share_code: str, sphere_id: int, user_id: UserId | None, now: datetime
    ) -> BoardDTO:
        self._require_available()
        board = self._boards.read_by_share_code(
            share_code=share_code, sphere_id=sphere_id
        )
        if user_id is not None:
            self._boards.record_visit(pk=board.pk, user_id=user_id, now=now)
        return board

    def bootstrap(
        self,
        *,
        share_code: str,
        sphere_id: int,
        user_id: UserId | None,
        guest: BoardGuestDTO,
        requested_name: str | None,
        client_ip: str,
        now: datetime,
    ) -> BoardBootstrapDTO:
        """Sign a pass onto the board for whoever is asking.

        A member is named by their account. A guest keeps the id and name the
        session remembers, and a name given now replaces the remembered one.

        Raises:
            BoardThrottledError: the address asked too often just now.
            BoardNameRequiredError: a guest with no name given or remembered.

        Returns:
            The pass, where to use it, and who it names.
        """
        worker = self._require_available()
        self._throttle(client_ip=client_ip, now=now)
        board = self._boards.read_by_share_code(
            share_code=share_code, sphere_id=sphere_id
        )
        person = self._person(
            board=board, user_id=user_id, guest=guest, requested_name=requested_name
        )
        issued_at = int(now.timestamp())
        token = self._signer.sign(
            BoardPassClaims(
                iss="ludamus",
                aud="board",
                sub=person.id,
                board=str(board.pk),
                link=board.link_version,
                name=person.name,
                owner=person.owner,
                iat=issued_at,
                exp=int((now + BOARD_PASS_LIFETIME).timestamp()),
            )
        )
        logger.info(
            "Board pass issued",
            extra={
                "board_id": board.pk,
                "person_kind": "member" if user_id is not None else "guest",
                "owner": person.owner,
            },
        )
        room = f"/rooms/{board.pk}"
        return BoardBootstrapDTO(
            pass_token=token,
            socket_url=f"{worker.socket_origin}{room}",
            http_url=f"{worker.http_origin}{room}",
            person=person,
            title=board.title,
        )

    def _person(
        self,
        *,
        board: BoardDTO,
        user_id: UserId | None,
        guest: BoardGuestDTO,
        requested_name: str | None,
    ) -> BoardPersonDTO:
        if user_id is not None:
            name = " ".join(self._boards.read_user_name(user_id).split())
            return BoardPersonDTO(
                id=f"{_MEMBER}{user_id}",
                name=name[:BOARD_NAME_MAX_LENGTH],
                owner=board.creator_id == user_id,
            )
        if requested_name is not None:
            name = clean_display_name(requested_name)
        elif guest.name is not None:
            try:
                name = clean_display_name(guest.name)
            except BoardNameInvalidError as exception:
                raise BoardNameRequiredError from exception
        else:
            raise BoardNameRequiredError
        guest_id = (
            guest.id
            if guest.id is not None and guest.id.startswith(_GUEST)
            else f"{_GUEST}{token_urlsafe(12)}"
        )
        return BoardPersonDTO(id=guest_id, name=name, owner=False)

    def _throttle(self, *, client_ip: str, now: datetime) -> None:
        # The address lives in the cache for one window, hashed, and nowhere
        # else.
        window = int(now.timestamp()) // BOARD_BOOTSTRAP_WINDOW_SECONDS
        address = sha256(client_ip.encode()).hexdigest()
        key = f"board_bootstrap_rate:{window}:{address}"
        count = self._cache.get(key)
        if (used := count if isinstance(count, int) else 0) >= BOARD_BOOTSTRAP_LIMIT:
            logger.warning("Board pass refused: too many requests")
            raise BoardThrottledError
        self._cache.set(key, used + 1, timeout=BOARD_BOOTSTRAP_WINDOW_SECONDS)

    def read_owned(self, *, pk: int, sphere_id: int, user_id: UserId) -> BoardDTO:
        self._require_available()
        return self._boards.read_owned(pk=pk, sphere_id=sphere_id, creator_id=user_id)

    def rename(
        self, *, pk: int, sphere_id: int, user_id: UserId, title: str
    ) -> BoardDTO:
        cleaned = _clean_title(title)
        with self._transaction.atomic():
            board = self.read_owned(pk=pk, sphere_id=sphere_id, user_id=user_id)
            self._boards.rename(pk=board.pk, title=cleaned)
            return self.read_owned(pk=pk, sphere_id=sphere_id, user_id=user_id)

    def reset_link(self, *, pk: int, sphere_id: int, user_id: UserId) -> BoardDTO:
        """Give the board a new link and move it to a new link version.

        The Worker drops every connection made with an older version as soon
        as a pass with the new one arrives, so guests who had only the old
        link are out.

        Returns:
            The board with its new share code and link version.
        """
        with self._transaction.atomic():
            board = self.read_owned(pk=pk, sphere_id=sphere_id, user_id=user_id)
            reset = self._boards.reset_link(pk=board.pk, share_code=_new_share_code())
        logger.info(
            "Board link reset",
            extra={
                "board_id": reset.pk,
                "link_version": reset.link_version,
                "user_id": user_id,
            },
        )
        return reset

    def delete(self, *, pk: int, sphere_id: int, user_id: UserId) -> None:
        with self._transaction.atomic():
            board = self.read_owned(pk=pk, sphere_id=sphere_id, user_id=user_id)
            self._boards.delete(board.pk)
        logger.info(
            "Board deleted",
            extra={"board_id": board.pk, "sphere_id": sphere_id, "user_id": user_id},
        )

    def list_mine(self, *, sphere_id: int, user_id: UserId) -> list[BoardListItemDTO]:
        if not self.available():
            return []
        return self._boards.list_for(sphere_id=sphere_id, user_id=user_id)
