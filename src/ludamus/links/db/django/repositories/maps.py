from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import transaction

from ludamus.links.db.django.models import EventMap, EventMapPage, Space
from ludamus.links.db.django.repositories.storage import (
    delete_stored_file_on_commit,
    with_original_names,
)
from ludamus.pacts import NotFoundError
from ludamus.pacts.maps import (
    EventMapPageDTO,
    EventMapRecordDTO,
    EventMapRepositoryProtocol,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ludamus.pacts.legacy import UploadedFileProtocol


def _to_dto(event_map: EventMap) -> EventMapRecordDTO:
    return EventMapRecordDTO(
        pk=event_map.pk,
        event_id=event_map.event_id,
        name=event_map.name,
        pages=[
            EventMapPageDTO(
                pk=page.pk,
                image_url=page.image_url,
                image_original_name=page.image_original_name,
            )
            for page in event_map.pages.all()
        ],
        space_pks=[space.pk for space in event_map.spaces.all()],
    )


def _event_map(pk: int, *, lock: bool = False) -> EventMap:
    queryset = EventMap.objects.prefetch_related("spaces", "pages")
    if lock:
        queryset = queryset.select_for_update()
    try:
        return queryset.get(pk=pk)
    except EventMap.DoesNotExist as exception:
        raise NotFoundError from exception


def _write_pages(event_map: EventMap, images: Sequence[UploadedFileProtocol]) -> None:
    stranded = [(page.image, page.image.name) for page in event_map.pages.all()]
    event_map.pages.all().delete()
    EventMapPage.objects.bulk_create(
        EventMapPage(
            event_map=event_map,
            order=order,
            **with_original_names(EventMapPage, {"image": image}),
        )
        for order, image in enumerate(images)
    )
    for field_file, stored_name in stranded:
        if stored_name:
            delete_stored_file_on_commit(field_file, stored_name)


class EventMapRepository(EventMapRepositoryProtocol):
    @staticmethod
    def list_for_event(event_pk: int) -> list[EventMapRecordDTO]:
        maps = EventMap.objects.filter(event_id=event_pk).prefetch_related(
            "spaces", "pages"
        )
        return [_to_dto(event_map) for event_map in maps]

    @staticmethod
    def exists_for_event(event_pk: int) -> bool:
        return EventMap.objects.filter(event_id=event_pk).exists()

    @staticmethod
    def read(pk: int) -> EventMapRecordDTO:
        return _to_dto(_event_map(pk))

    @transaction.atomic
    def create(
        self, *, event_pk: int, name: str, images: Sequence[UploadedFileProtocol]
    ) -> EventMapRecordDTO:
        event_map = EventMap(event_id=event_pk, name=name)
        event_map.save()
        _write_pages(event_map, images)
        return self.read(event_map.pk)

    @transaction.atomic
    def update(
        self, *, pk: int, name: str, images: Sequence[UploadedFileProtocol] | None
    ) -> EventMapRecordDTO:
        event_map = _event_map(pk, lock=True)
        event_map.name = name
        event_map.save(update_fields=["name", "modification_time"])
        if images is not None:
            _write_pages(event_map, images)
        return self.read(pk)

    @staticmethod
    def set_spaces(pk: int, space_pks: list[int]) -> None:
        _event_map(pk).spaces.set(Space.objects.filter(pk__in=space_pks))

    @staticmethod
    @transaction.atomic
    def delete(pk: int) -> None:
        # Locked like update: an edit committing at the same moment would
        event_map = _event_map(pk, lock=True)
        stranded = [(page.image, page.image.name) for page in event_map.pages.all()]
        event_map.delete()
        for field_file, stored_name in stranded:
            if stored_name:
                delete_stored_file_on_commit(field_file, stored_name)
