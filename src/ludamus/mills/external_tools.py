from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.pacts.external_tools import ExternalToolServiceProtocol

if TYPE_CHECKING:
    from ludamus.pacts.external_tools import (
        ExternalToolDTO,
        ExternalToolRepositoryProtocol,
    )


class ExternalToolService(ExternalToolServiceProtocol):
    def __init__(self, repo: ExternalToolRepositoryProtocol) -> None:
        self._repo = repo

    def read_active(self, slug: str) -> ExternalToolDTO:
        return self._repo.read_active(slug)
