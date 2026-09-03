from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.pacts import NotFoundError
from ludamus.pacts.maps import EventMapsServiceProtocol, MapIndexDTO

if TYPE_CHECKING:
    from ludamus.pacts import SpaceRepositoryProtocol
    from ludamus.pacts.legacy import UploadedFileProtocol
    from ludamus.pacts.maps import EventMapDTO, EventMapRepositoryProtocol
    from ludamus.pacts.services import TransactionProtocol


class EventMapsService(EventMapsServiceProtocol):
    def __init__(
        self,
        transaction: TransactionProtocol,
        maps: EventMapRepositoryProtocol,
        spaces: SpaceRepositoryProtocol,
    ) -> None:
        self._transaction = transaction
        self._maps = maps
        self._spaces = spaces

    def list_for_event(self, event_pk: int) -> list[EventMapDTO]:
        return self._maps.list_for_event(event_pk)

    def read(self, *, event_pk: int, pk: int) -> EventMapDTO:
        # Panel access proves the organizer manages this event, not that the
        # pk in the URL belongs to it: a map of another event reads as absent.
        event_map = self._maps.read(pk)
        if event_map.event_id != event_pk:
            raise NotFoundError
        return event_map

    def create(
        self, *, event_pk: int, name: str, image: UploadedFileProtocol
    ) -> EventMapDTO:
        return self._maps.create(event_pk=event_pk, name=name, image=image)

    def update(
        self, *, event_pk: int, pk: int, name: str, image: UploadedFileProtocol | None
    ) -> EventMapDTO:
        with self._transaction.atomic():
            self.read(event_pk=event_pk, pk=pk)
            return self._maps.update(pk=pk, name=name, image=image)

    def attach_spaces(self, *, event_pk: int, pk: int, space_pks: list[int]) -> None:
        # Body ids are as unproven as URL ids: a space of another event in the
        # posted list refuses the whole write rather than pinning it quietly.
        with self._transaction.atomic():
            self.read(event_pk=event_pk, pk=pk)
            event_space_pks = {
                space.pk for space in self._spaces.list_by_event(event_pk)
            }
            if not set(space_pks) <= event_space_pks:
                raise NotFoundError
            self._maps.set_spaces(pk, space_pks)

    def delete(self, *, event_pk: int, pk: int) -> None:
        with self._transaction.atomic():
            self.read(event_pk=event_pk, pk=pk)
            self._maps.delete(pk)

    def index(self, event_pk: int) -> MapIndexDTO:
        # A map drawn for a venue covers every room inside it, so a room with
        # no map of its own inherits the nearest ancestor's. The first map in
        # display order wins when several show the same space.
        if not (maps := self._maps.list_for_event(event_pk)):
            return MapIndexDTO(has_maps=False, map_pk_by_space={})
        direct: dict[int, int] = {}
        for event_map in maps:
            for space_pk in event_map.space_pks:
                direct.setdefault(space_pk, event_map.pk)

        spaces = self._spaces.list_by_event(event_pk)
        parent_of = {space.pk: space.parent_id for space in spaces}
        resolved: dict[int, int] = {}
        for space in spaces:
            current: int | None = space.pk
            while current is not None and current not in direct:
                current = parent_of.get(current)
            if current is not None:
                resolved[space.pk] = direct[current]
        return MapIndexDTO(has_maps=True, map_pk_by_space=resolved)
