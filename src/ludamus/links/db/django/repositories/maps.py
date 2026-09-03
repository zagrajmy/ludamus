from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models import Max

from ludamus.links.db.django.models import EventMap, Space
from ludamus.links.db.django.repositories.storage import (
    delete_stored_file,
    save_replacing_files,
    with_original_names,
)
from ludamus.pacts import NotFoundError
from ludamus.pacts.maps import (
    EventMapDTO,
    EventMapRepositoryProtocol,
    MapSpaceDTO,
    MapTreeNodeDTO,
)

if TYPE_CHECKING:
    from ludamus.pacts.legacy import UploadedFileProtocol


class _SpaceTree:
    # The event's whole tree, loaded once, so every map's label list and file
    # tree come from Python walks rather than a query per node.
    def __init__(self, event_pk: int) -> None:
        self.by_pk = {
            space.pk: space
            for space in (
                Space.objects.filter(event_id=event_pk)
                .only("pk", "name", "parent_id", "order")
                .order_by("order", "name")
            )
        }
        self.children: dict[int | None, list[int]] = defaultdict(list)
        for space in self.by_pk.values():
            self.children[space.parent_id].append(space.pk)

    def path(self, pk: int) -> str:
        space = self.by_pk[pk]
        if space.parent_id is None or space.parent_id not in self.by_pk:
            return space.name
        return f"{self.path(space.parent_id)} > {space.name}"

    def tree(self, attached: set[int]) -> list[MapTreeNodeDTO]:
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
                children=[
                    build(child) for child in self.children[pk] if child in visible
                ],
            )

        return [build(pk) for pk in self.children[None] if pk in visible]


def _to_dto(event_map: EventMap, tree: _SpaceTree) -> EventMapDTO:
    attached = {space.pk for space in event_map.spaces.all() if space.pk in tree.by_pk}
    return EventMapDTO(
        pk=event_map.pk,
        event_id=event_map.event_id,
        name=event_map.name,
        image_url=event_map.image_url,
        image_original_name=event_map.image_original_name,
        spaces=[
            MapSpaceDTO(pk=pk, name=tree.path(pk))
            for pk in sorted(attached, key=tree.path)
        ],
        tree=tree.tree(attached),
    )


class EventMapRepository(EventMapRepositoryProtocol):
    @staticmethod
    def list_for_event(event_pk: int) -> list[EventMapDTO]:
        maps = list(
            EventMap.objects.filter(event_id=event_pk).prefetch_related("spaces")
        )
        tree = _SpaceTree(event_pk)
        return [_to_dto(event_map, tree) for event_map in maps]

    @staticmethod
    def read(pk: int) -> EventMapDTO:
        try:
            event_map = EventMap.objects.prefetch_related("spaces").get(pk=pk)
        except EventMap.DoesNotExist as exception:
            raise NotFoundError from exception
        return _to_dto(event_map, _SpaceTree(event_map.event_id))

    def create(
        self, *, event_pk: int, name: str, image: UploadedFileProtocol
    ) -> EventMapDTO:
        top = EventMap.objects.filter(event_id=event_pk).aggregate(top=Max("order"))
        event_map = EventMap(
            event_id=event_pk,
            order=(top["top"] if top["top"] is not None else -1) + 1,
            **with_original_names(EventMap, {"name": name, "image": image}),
        )
        event_map.save()
        return self.read(event_map.pk)

    @transaction.atomic
    def update(
        self, *, pk: int, name: str, image: UploadedFileProtocol | None
    ) -> EventMapDTO:
        try:
            event_map = EventMap.objects.select_for_update().get(pk=pk)
        except EventMap.DoesNotExist as exception:
            raise NotFoundError from exception
        fields: dict[str, UploadedFileProtocol | str] = {"name": name}
        if image is not None:
            fields["image"] = image
        save_replacing_files(event_map, fields)
        return self.read(pk)

    @staticmethod
    def set_spaces(pk: int, space_pks: list[int]) -> None:
        try:
            event_map = EventMap.objects.get(pk=pk)
        except EventMap.DoesNotExist as exception:
            raise NotFoundError from exception
        event_map.spaces.set(Space.objects.filter(pk__in=space_pks))

    @staticmethod
    def delete(pk: int) -> None:
        try:
            event_map = EventMap.objects.get(pk=pk)
        except EventMap.DoesNotExist as exception:
            raise NotFoundError from exception
        stored_name = event_map.image.name
        event_map.delete()
        if stored_name:
            delete_stored_file(event_map.image, stored_name)
