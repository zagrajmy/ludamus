"""Event maps: uploaded venue plans and the spaces each one shows."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ludamus.pacts.legacy import UploadedFileProtocol


class MapTreeNodeDTO(BaseModel):
    # One row of the venue tree beside a map. An ancestor that is not attached
    # itself is still drawn, so the reader sees where a room sits, but only an
    # attached node with a filter the schedule understands becomes a link.
    pk: int
    name: str
    attached: bool
    has_children: bool
    # The `?space=` value that narrows the schedule to this node, or None when
    # the schedule cannot express it (a venue whose rooms sit further down).
    schedule_filter: str | None
    children: list[MapTreeNodeDTO]


class EventMapPageDTO(BaseModel):
    # One picture of a plan. A map that runs to several pages — a site plan and
    # its legend — keeps them here in reading order.
    pk: int
    image_url: str
    image_original_name: str = ""


class EventMapRecordDTO(BaseModel):
    pk: int
    event_id: int
    name: str
    pages: list[EventMapPageDTO] = Field(default_factory=list)
    space_pks: list[int] = Field(default_factory=list)


class EventMapDTO(EventMapRecordDTO):
    tree: list[MapTreeNodeDTO] = Field(default_factory=list)


class EventMapRepositoryProtocol(Protocol):
    @staticmethod
    def list_for_event(event_pk: int) -> list[EventMapRecordDTO]: ...
    @staticmethod
    def exists_for_event(event_pk: int) -> bool: ...
    @staticmethod
    def read(pk: int) -> EventMapRecordDTO: ...
    def create(
        self, *, event_pk: int, name: str, images: Sequence[UploadedFileProtocol]
    ) -> EventMapRecordDTO: ...
    def update(
        self, *, pk: int, name: str, images: Sequence[UploadedFileProtocol] | None
    ) -> EventMapRecordDTO: ...
    @staticmethod
    def set_spaces(pk: int, space_pks: list[int]) -> None: ...
    @staticmethod
    def delete(pk: int) -> None: ...


class EventMapsServiceProtocol(Protocol):
    def list_for_event(self, event_pk: int) -> list[EventMapDTO]: ...
    def read(self, *, event_pk: int, pk: int) -> EventMapRecordDTO: ...
    def create(
        self, *, event_pk: int, name: str, images: Sequence[UploadedFileProtocol]
    ) -> EventMapRecordDTO: ...
    def update(
        self,
        *,
        event_pk: int,
        pk: int,
        name: str,
        images: Sequence[UploadedFileProtocol] | None,
    ) -> EventMapRecordDTO: ...
    def attach_spaces(
        self, *, event_pk: int, pk: int, space_pks: list[int]
    ) -> None: ...
    def delete(self, *, event_pk: int, pk: int) -> None: ...
    def has_maps(self, event_pk: int) -> bool: ...
    def map_pk_for_space(self, *, event_pk: int, space_pk: int) -> int | None: ...
