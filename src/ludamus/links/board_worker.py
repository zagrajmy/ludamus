"""Django's calls to the board Worker, server to server."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import requests

from ludamus.pacts.board import BoardWorkerUnavailableError

if TYPE_CHECKING:
    from ludamus.pacts.board import BoardWorkerDTO

# Cloudflare answers from the edge; a wipe that takes longer is stuck, and
# the person deleting the board should not wait on it.
_TIMEOUT_SECONDS = 10


class BoardWorkerClient:
    def __init__(self, worker: BoardWorkerDTO | None) -> None:
        self._worker = worker

    def wipe(self, *, board_id: int, token: str) -> None:
        if self._worker is None:
            raise BoardWorkerUnavailableError
        try:
            response = requests.post(
                f"{self._worker.http_origin}/rooms/{board_id}/delete",
                headers={"Authorization": f"Bearer {token}"},
                timeout=_TIMEOUT_SECONDS,
            )
        except requests.RequestException as error:
            raise BoardWorkerUnavailableError from error
        if response.status_code != HTTPStatus.NO_CONTENT:
            raise BoardWorkerUnavailableError(response.status_code)
