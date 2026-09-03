from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models import Max

from ludamus.links.db.django.models import EventMap, Space
from ludamus.links.db.django.repositories.storage import (
    delete_stored_file,
    save_replacing_files_on_commit,
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
        try:
            event_map = EventMap.objects.prefetch_related("spaces").get(pk=pk)
        except EventMap.DoesNotExist as exception:
            raise NotFoundError from exception
        return _to_dto(event_map)

    def create(
        self, *, event_pk: int, name: str, image: UploadedFileProtocol
    ) -> EventMapRecordDTO:
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
    ) -> EventMapRecordDTO:
        try:
            event_map = EventMap.objects.select_for_update().get(pk=pk)
        except EventMap.DoesNotExist as exception:
            raise NotFoundError from exception
        fields: dict[str, UploadedFileProtocol | str] = {"name": name}
        if image is not None:
            fields["image"] = image
        save_replacing_files_on_commit(event_map, fields)
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
            transaction.on_commit(
                partial(delete_stored_file, event_map.image, stored_name)
            )
