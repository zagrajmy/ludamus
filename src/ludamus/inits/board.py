"""Where browsers find the board Worker, from settings."""

from __future__ import annotations

from django.conf import settings

from ludamus.links.parley_worker import is_local
from ludamus.pacts.board import BoardWorkerDTO


def board_worker() -> BoardWorkerDTO | None:
    # The board signs with Parley's key, so both have to be there.
    host: str = settings.BOARD_HOST
    private_key: str = settings.PARLEY_SIGNING_PRIVATE_KEY
    if not (host and private_key):
        return None
    local = is_local(host)
    return BoardWorkerDTO(
        http_origin=f"{'http' if local else 'https'}://{host}",
        socket_origin=f"{'ws' if local else 'wss'}://{host}",
    )
