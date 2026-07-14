from typing import TYPE_CHECKING

from ludamus.pacts.chronology import PartyDetailDTO, PartySessionHistoryServiceProtocol

if TYPE_CHECKING:
    from ludamus.pacts.chronology import PartySessionHistoryRepositoryProtocol
    from ludamus.pacts.party import PartyRepositoryProtocol


class PartySessionHistoryService(PartySessionHistoryServiceProtocol):
    def __init__(
        self,
        parties: PartyRepositoryProtocol,
        history: PartySessionHistoryRepositoryProtocol,
    ) -> None:
        self._parties = parties
        self._history = history

    def read_detail(self, *, party_pk: int, viewer_pk: int) -> PartyDetailDTO | None:
        party = self._parties.read_for_viewer(party_pk=party_pk, viewer_pk=viewer_pk)
        if party is None:
            return None
        return PartyDetailDTO(
            party=party,
            history=self._history.list_for_party(
                party_pk=party_pk, viewer_pk=viewer_pk
            ),
        )
