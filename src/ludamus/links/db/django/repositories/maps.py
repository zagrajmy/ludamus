from __future__ import annotations

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
from ludamus.pacts.maps import EventMapDTO, EventMapRepositoryProtocol, MapSpaceDTO

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ludamus.pacts.legacy import UploadedFileProtocol
    from ludamus.pacts.maps import EventMapInputDTO


def _space_labels(event_pk: int) -> tuple[dict[int, str], set[int]]:
    # One query for the whole tree: the path label of every space and the pks
    # that group other spaces, so a map's list needs no walk of its own.
    spaces = list(
        Space.objects.filter(event_id=event_pk).only("pk", "name", "parent_id")
    )
    by_pk = {space.pk: space for space in spaces}
    parents = {space.parent_id for space in spaces if space.parent_id is not None}

    def path(space: Space) -> str:
        parent = by_pk.get(space.parent_id) if space.parent_id else None
        return f"{path(parent)} > {space.name}" if parent else space.name

    return {space.pk: path(space) for space in spaces}, parents


def _to_dto(
    event_map: EventMap,
    spaces: Iterable[Space],
    labels: dict[int, str],
    parents: set[int],
) -> EventMapDTO:
    return EventMapDTO(
        pk=event_map.pk,
        event_id=event_map.event_id,
        name=event_map.name,
        image_url=event_map.image_url,
        image_original_name=event_map.image_original_name,
        spaces=[
            MapSpaceDTO(
                pk=space.pk,
                name=labels.get(space.pk, space.name),
                has_children=space.pk in parents,
            )
            for space in spaces
        ],
    )


class EventMapRepository(EventMapRepositoryProtocol):
    @staticmethod
    def list_for_event(event_pk: int) -> list[EventMapDTO]:
        maps = list(
            EventMap.objects.filter(event_id=event_pk).prefetch_related("spaces")
        )
        labels, parents = _space_labels(event_pk)
        return [
            _to_dto(
                event_map=event_map,
                spaces=event_map.spaces.all(),
                labels=labels,
                parents=parents,
            )
            for event_map in maps
        ]

    @staticmethod
    def read(pk: int) -> EventMapDTO:
        try:
            event_map = EventMap.objects.prefetch_related("spaces").get(pk=pk)
        except EventMap.DoesNotExist as exception:
            raise NotFoundError from exception
        labels, parents = _space_labels(event_map.event_id)
        return _to_dto(
            event_map=event_map,
            spaces=event_map.spaces.all(),
            labels=labels,
            parents=parents,
        )

    @transaction.atomic
    def create(
        self, *, event_pk: int, data: EventMapInputDTO, image: UploadedFileProtocol
    ) -> EventMapDTO:
        top = EventMap.objects.filter(event_id=event_pk).aggregate(top=Max("order"))
        event_map = EventMap(
            event_id=event_pk,
            order=(top["top"] if top["top"] is not None else -1) + 1,
            **with_original_names(EventMap, {"name": data.name, "image": image}),
        )
        event_map.save()
        event_map.spaces.set(self._spaces(data.space_pks))
        return self.read(event_map.pk)

    @transaction.atomic
    def update(
        self, *, pk: int, data: EventMapInputDTO, image: UploadedFileProtocol | None
    ) -> EventMapDTO:
        try:
            event_map = EventMap.objects.select_for_update().get(pk=pk)
        except EventMap.DoesNotExist as exception:
            raise NotFoundError from exception
        fields: dict[str, UploadedFileProtocol | str] = {"name": data.name}
        if image is not None:
            fields["image"] = image
        save_replacing_files(event_map, fields)
        event_map.spaces.set(self._spaces(data.space_pks))
        return self.read(pk)

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

    @staticmethod
    def _spaces(space_pks: list[int]) -> list[Space]:
        return list(Space.objects.filter(pk__in=space_pks))
