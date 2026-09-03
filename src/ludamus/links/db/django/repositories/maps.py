from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import transaction

from ludamus.links.db.django.models import EventMap, Space
from ludamus.links.db.django.repositories.storage import (
    delete_stored_file_on_commit,
    save_replacing_files,
    with_original_names,
)
from ludamus.pacts import NotFoundError
from ludamus.pacts.maps import EventMapRecordDTO, EventMapRepositoryProtocol

if TYPE_CHECKING:
    from ludamus.pacts.legacy import UploadedFileProtocol


def _to_dto(event_map: EventMap) -> EventMapRecordDTO:
    return EventMapRecordDTO(
        pk=event_map.pk,
        event_id=event_map.event_id,
        name=event_map.name,
        image_url=event_map.image_url,
        image_original_name=event_map.image_original_name,
        space_pks=[space.pk for space in event_map.spaces.all()],
    )


def _event_map(pk: int, *, lock: bool = False) -> EventMap:
    queryset = EventMap.objects.prefetch_related("spaces")
    if lock:
        queryset = queryset.select_for_update()
    try:
        return queryset.get(pk=pk)
    except EventMap.DoesNotExist as exception:
        raise NotFoundError from exception


class EventMapRepository(EventMapRepositoryProtocol):
    @staticmethod
    def list_for_event(event_pk: int) -> list[EventMapRecordDTO]:
        maps = EventMap.objects.filter(event_id=event_pk).prefetch_related("spaces")
        return [_to_dto(event_map) for event_map in maps]

    @staticmethod
    def exists_for_event(event_pk: int) -> bool:
        return EventMap.objects.filter(event_id=event_pk).exists()

    @staticmethod
    def read(pk: int) -> EventMapRecordDTO:
        return _to_dto(_event_map(pk))

    def create(
        self, *, event_pk: int, name: str, image: UploadedFileProtocol
    ) -> EventMapRecordDTO:
        event_map = EventMap(
            event_id=event_pk,
            **with_original_names(EventMap, {"name": name, "image": image}),
        )
        event_map.save()
        return self.read(event_map.pk)

    @transaction.atomic
    def update(
        self, *, pk: int, name: str, image: UploadedFileProtocol | None
    ) -> EventMapRecordDTO:
        event_map = _event_map(pk, lock=True)
        fields: dict[str, UploadedFileProtocol | str] = {"name": name}
        if image is not None:
            fields["image"] = image
        save_replacing_files(event_map, fields)
        return self.read(pk)

    @staticmethod
    def set_spaces(pk: int, space_pks: list[int]) -> None:
        _event_map(pk).spaces.set(Space.objects.filter(pk__in=space_pks))

    @staticmethod
    def delete(pk: int) -> None:
        event_map = _event_map(pk)
        stored_name = event_map.image.name
        event_map.delete()
        if stored_name:
            delete_stored_file_on_commit(event_map.image, stored_name)
