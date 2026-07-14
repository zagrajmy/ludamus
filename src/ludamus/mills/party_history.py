from typing import TYPE_CHECKING

from ludamus.pacts.chronology import PartySessionHistoryServiceProtocol

if TYPE_CHECKING:
    from ludamus.pacts.chronology import (
        PartyEventHistoryDTO,
        PartySessionHistoryRepositoryProtocol,
    )
    from ludamus.pacts.party import PartyRepositoryProtocol


class PartySessionHistoryService(PartySessionHistoryServiceProtocol):
    def __init__(
        self,
        parties: PartyRepositoryProtocol,
        history: PartySessionHistoryRepositoryProtocol,
    ) -> None:
        self._parties = parties
        self._history = history

    def list_for_party(
        self, *, party_pk: int, viewer_pk: int
    ) -> list[PartyEventHistoryDTO] | None:
        if not self._parties.can_view(party_pk=party_pk, viewer_pk=viewer_pk):
            return None
        return self._history.list_for_party(party_pk=party_pk, viewer_pk=viewer_pk)
