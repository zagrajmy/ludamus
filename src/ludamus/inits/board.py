"""Where the board app runs, from settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings

from ludamus.links.board_worker import BoardWorkerClient
from ludamus.links.cache import DjangoCache
from ludamus.links.encryption import JwtSigner
from ludamus.links.parley_worker import is_local
from ludamus.mills.board import BoardService
from ludamus.pacts.board import BoardRepositoryProtocol, BoardWorkerDTO

if TYPE_CHECKING:
    from ludamus.pacts.services import TransactionProtocol


def board_worker() -> BoardWorkerDTO | None:
    # The board signs with Parley's key, so both have to be there.
    host: str = settings.BOARD_HOST
    private_key: str = settings.PARLEY_SIGNING_PRIVATE_KEY
    if not (host and private_key):
        return None
    return BoardWorkerDTO(
        http_origin=f"{'http' if is_local(host) else 'https'}://{host}"
    )


def board_service(
    *, transaction: TransactionProtocol, boards: BoardRepositoryProtocol
) -> BoardService:
    signing_private_key: str = settings.PARLEY_SIGNING_PRIVATE_KEY
    worker = board_worker()
    return BoardService(
        transaction=transaction,
        boards=boards,
        signer=JwtSigner(signing_private_key),
        cache=DjangoCache(),
        rooms=BoardWorkerClient(worker),
        worker=worker,
    )
