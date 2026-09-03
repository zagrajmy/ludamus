"""Event maps: uploaded venue plans and the spaces each one shows."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from ludamus.pacts.legacy import UploadedFileProtocol


class MapSpaceDTO(BaseModel):
    pk: int
    name: str


class MapTreeNodeDTO(BaseModel):
    pk: int
    name: str
    attached: bool
    has_children: bool
    children: list[MapTreeNodeDTO]


class EventMapRecordDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pk: int
    event_id: int
    name: str
    image_url: str
    image_original_name: str = ""
    space_pks: list[int] = Field(default_factory=list)


class EventMapDTO(BaseModel):
    pk: int
    event_id: int
    name: str
    image_url: str
    image_original_name: str = ""
    spaces: list[MapSpaceDTO] = Field(default_factory=list)
    tree: list[MapTreeNodeDTO] = Field(default_factory=list)

    @property
    def space_pks(self) -> list[int]:
        return [space.pk for space in self.spaces]


class EventMapRepositoryProtocol(Protocol):
    @staticmethod
    def list_for_event(event_pk: int) -> list[EventMapRecordDTO]: ...
    @staticmethod
    def exists_for_event(event_pk: int) -> bool: ...
    @staticmethod
    def read(pk: int) -> EventMapRecordDTO: ...
    def create(
        self, *, event_pk: int, name: str, image: UploadedFileProtocol
    ) -> EventMapRecordDTO: ...
    def update(
        self, *, pk: int, name: str, image: UploadedFileProtocol | None
    ) -> EventMapRecordDTO: ...
    @staticmethod
    def set_spaces(pk: int, space_pks: list[int]) -> None: ...
    @staticmethod
    def delete(pk: int) -> None: ...


class EventMapsServiceProtocol(Protocol):
    def list_for_event(self, event_pk: int) -> list[EventMapDTO]: ...
    def read(self, *, event_pk: int, pk: int) -> EventMapRecordDTO: ...
    def create(
        self, *, event_pk: int, name: str, image: UploadedFileProtocol
    ) -> EventMapRecordDTO: ...
    def update(
        self, *, event_pk: int, pk: int, name: str, image: UploadedFileProtocol | None
    ) -> EventMapRecordDTO: ...
    def attach_spaces(
        self, *, event_pk: int, pk: int, space_pks: list[int]
    ) -> None: ...
    def delete(self, *, event_pk: int, pk: int) -> None: ...
    def has_maps(self, event_pk: int) -> bool: ...
    def map_pk_for_space(self, *, event_pk: int, space_pk: int) -> int | None: ...
