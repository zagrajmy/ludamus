from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from ludamus.pacts import NotFoundError
from ludamus.pacts.maps import EventMapDTO, EventMapsServiceProtocol, MapTreeNodeDTO

if TYPE_CHECKING:
    from ludamus.pacts import SpaceDTO, SpaceRepositoryProtocol
    from ludamus.pacts.legacy import UploadedFileProtocol
    from ludamus.pacts.maps import EventMapRecordDTO, EventMapRepositoryProtocol
    from ludamus.pacts.services import TransactionProtocol


class _SpaceTree:
    def __init__(self, spaces: list[SpaceDTO]) -> None:
        self.by_pk = {space.pk: space for space in spaces}
        self.children: dict[int | None, list[int]] = defaultdict(list)
        for space in spaces:
            self.children[space.parent_id].append(space.pk)

    def schedule_filter(self, pk: int) -> str | None:
        # The schedule filters a session by its room or by the room's direct
        # parent (`venue:<pk>`), the same two facts its cards carry. A venue
        # whose rooms sit deeper has no filter, so its node stays plain text.
        if not (children := self.children.get(pk, [])):
            return str(pk)
        if all(not self.children.get(child) for child in children):
            return f"venue:{pk}"
        return None

    def for_map(self, attached: set[int]) -> list[MapTreeNodeDTO]:
        # Attached nodes and every ancestor of one, in the tree's own order;
        # nothing else, so a map of one room does not draw the whole building.
        visible: set[int] = set()
        for pk in attached:
            current: int | None = pk
            while current is not None and current in self.by_pk:
                visible.add(current)
                current = self.by_pk[current].parent_id

        def build(pk: int) -> MapTreeNodeDTO:
            return MapTreeNodeDTO(
                pk=pk,
                name=self.by_pk[pk].name,
                attached=pk in attached,
                has_children=bool(self.children.get(pk)),
                schedule_filter=self.schedule_filter(pk),
                children=[
                    build(child) for child in self.children[pk] if child in visible
                ],
            )

        return [build(pk) for pk in self.children[None] if pk in visible]

    def nearest(self, pk: int, direct: dict[int, int]) -> int | None:
        current: int | None = pk
        while current is not None and current not in direct:
            space = self.by_pk.get(current)
            current = space.parent_id if space else None
        return direct.get(current) if current is not None else None


def _present_map(event_map: EventMapRecordDTO, tree: _SpaceTree) -> EventMapDTO:
    attached = {pk for pk in event_map.space_pks if pk in tree.by_pk}
    return EventMapDTO(
        pk=event_map.pk,
        event_id=event_map.event_id,
        name=event_map.name,
        image_url=event_map.image_url,
        image_original_name=event_map.image_original_name,
        space_pks=event_map.space_pks,
        tree=tree.for_map(attached),
    )


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
        if not (maps := self._maps.list_for_event(event_pk)):
            return []
        tree = _SpaceTree(self._spaces.list_by_event(event_pk))
        return [_present_map(event_map, tree) for event_map in maps]

    def read(self, *, event_pk: int, pk: int) -> EventMapRecordDTO:
        event_map = self._maps.read(pk)
        if event_map.event_id != event_pk:
            raise NotFoundError
        return event_map

    def create(
        self, *, event_pk: int, name: str, image: UploadedFileProtocol
    ) -> EventMapRecordDTO:
        return self._maps.create(event_pk=event_pk, name=name, image=image)

    def update(
        self, *, event_pk: int, pk: int, name: str, image: UploadedFileProtocol | None
    ) -> EventMapRecordDTO:
        with self._transaction.atomic():
            self.read(event_pk=event_pk, pk=pk)
            return self._maps.update(pk=pk, name=name, image=image)

    def attach_spaces(self, *, event_pk: int, pk: int, space_pks: list[int]) -> None:
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

    def has_maps(self, event_pk: int) -> bool:
        return self._maps.exists_for_event(event_pk)

    def map_pk_for_space(self, *, event_pk: int, space_pk: int) -> int | None:
        maps = self._maps.list_for_event(event_pk)
        direct: dict[int, int] = {}
        for event_map in maps:
            for attached_pk in event_map.space_pks:
                direct.setdefault(attached_pk, event_map.pk)
        if not direct:
            return None
        tree = _SpaceTree(self._spaces.list_by_event(event_pk))
        return tree.nearest(space_pk, direct)
