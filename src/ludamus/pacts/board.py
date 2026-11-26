"""The board: a shared whiteboard with dice, run by the board Worker."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from ludamus.pacts.ids import UserId

BOARD_TITLE_MAX_LENGTH = 80


class BoardDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pk: int
    sphere_id: int
    creator_id: int
    title: str
    share_code: str
    link_version: int
    creation_time: datetime


class BoardListItemDTO(BaseModel):
    pk: int
    title: str
    share_code: str
    is_owner: bool
    # When this person last opened it, or else when it was created.
    last_opened_at: datetime


class BoardPersonDTO(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)

    # "u:<user id>" for a member, "g:<random id>" for a guest.
    id: str
    name: str
    owner: bool


class BoardGuestDTO(BaseModel):
    """What the browser's session remembers of a guest, if anything."""

    id: str | None = None
    name: str | None = None


class BoardPassClaims(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)

    iss: str
    aud: str
    sub: str
    # The board's primary key, never its share code: a reset changes the code.
    board: str
    link: int
    name: str
    owner: bool
    iat: int
    exp: int


class BoardDeletionClaims(BaseModel):
    """Lets Django tell the Worker to wipe one board's room and roll log."""

    iss: str
    aud: str
    board: str
    iat: int
    exp: int


class BoardSphereDTO(BaseModel):
    """The sphere a board belongs to, as its people reach it."""

    name: str
    domain: str


class BoardBootstrapDTO(BaseModel):
    pass_token: str
    # The board's room on the board app's own origin: /rooms/<board id>.
    board_id: str
    person: BoardPersonDTO
    title: str
    sphere_name: str
    sphere_domain: str


class BoardWorkerDTO(BaseModel):
    """Where the board app runs: its Worker and its pages, scheme included."""

    http_origin: str


class BoardNameRequiredError(Exception):
    """A guest has no display name yet."""


class BoardNameInvalidError(Exception):
    """The display name given is empty, too long or not printable."""


class BoardTitleInvalidError(Exception):
    """The title is empty or too long."""


class BoardThrottledError(Exception):
    """Too many passes asked for from one address in a short time."""


class BoardWorkerUnavailableError(Exception):
    """The board Worker could not be reached, or refused the request."""


class BoardRepositoryProtocol(Protocol):
    @staticmethod
    def create(
        *, sphere_id: int, creator_id: UserId, title: str, share_code: str
    ) -> BoardDTO: ...
    @staticmethod
    def read_by_share_code(*, share_code: str, sphere_id: int) -> BoardDTO: ...
    @staticmethod
    def read_shared(share_code: str) -> BoardDTO: ...
    @staticmethod
    def read_sphere(sphere_id: int) -> BoardSphereDTO: ...
    @staticmethod
    def read_owned(*, pk: int, sphere_id: int, creator_id: UserId) -> BoardDTO: ...
    @staticmethod
    def rename(*, pk: int, title: str) -> None: ...
    @staticmethod
    def reset_link(*, pk: int, share_code: str) -> BoardDTO: ...
    @staticmethod
    def delete(pk: int) -> None: ...
    @staticmethod
    def record_visit(*, pk: int, user_id: UserId, now: datetime) -> None: ...
    @staticmethod
    def list_for(*, sphere_id: int, user_id: UserId) -> list[BoardListItemDTO]: ...
    @staticmethod
    def read_user_name(user_id: UserId) -> str: ...


class BoardSignerProtocol(Protocol):
    def sign(self, claims: BoardPassClaims | BoardDeletionClaims) -> str: ...


class BoardRoomsProtocol(Protocol):
    def wipe(self, *, board_id: int, token: str) -> None:
        """Close a board's connections and drop its document and roll log.

        Raises:
            BoardWorkerUnavailableError: the Worker did not confirm it.
        """


class BoardServiceProtocol(Protocol):
    def available(self) -> bool: ...
    def origin(self) -> str: ...
    def create(self, *, sphere_id: int, user_id: UserId, title: str) -> BoardDTO: ...
    def open(self, *, share_code: str, sphere_id: int) -> BoardDTO: ...
    def bootstrap(
        self,
        *,
        share_code: str,
        user_id: UserId | None,
        guest: BoardGuestDTO,
        requested_name: str | None,
        client_ip: str,
        now: datetime,
    ) -> BoardBootstrapDTO: ...
    def read_owned(self, *, pk: int, sphere_id: int, user_id: UserId) -> BoardDTO: ...
    def rename(
        self, *, pk: int, sphere_id: int, user_id: UserId, title: str
    ) -> BoardDTO: ...
    def reset_link(self, *, pk: int, sphere_id: int, user_id: UserId) -> BoardDTO: ...
    def delete(
        self, *, pk: int, sphere_id: int, user_id: UserId, now: datetime
    ) -> bool: ...
    def list_mine(
        self, *, sphere_id: int, user_id: UserId
    ) -> list[BoardListItemDTO]: ...
