"""Event maps: uploaded venue plans and the spaces each one shows."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from ludamus.pacts.legacy import UploadedFileProtocol


class MapSpaceDTO(BaseModel):
    # A space as the maps page lists it: the pk the schedule filter keys on,
    # the tree path a reader recognises it by, and whether it groups rooms —
    # a group is filtered as a venue, a room as itself.
    pk: int
    name: str
    has_children: bool


class EventMapDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pk: int
    event_id: int
    name: str
    image_url: str
    image_original_name: str = ""
    spaces: list[MapSpaceDTO] = []

    @property
    def space_names(self) -> list[str]:
        return [space.name for space in self.spaces]


class EventMapInputDTO(BaseModel):
    name: str
    space_pks: list[int]


class MapIndexDTO(BaseModel):
    # What the schedule needs from the maps in one read: whether there is a
    # maps page to link to at all, and which map each space is drawn on.
    has_maps: bool
    map_pk_by_space: dict[int, int]


class EventMapRepositoryProtocol(Protocol):
    @staticmethod
    def list_for_event(event_pk: int) -> list[EventMapDTO]: ...
    @staticmethod
    def read(pk: int) -> EventMapDTO: ...
    def create(
        self, *, event_pk: int, data: EventMapInputDTO, image: UploadedFileProtocol
    ) -> EventMapDTO: ...
    def update(
        self, *, pk: int, data: EventMapInputDTO, image: UploadedFileProtocol | None
    ) -> EventMapDTO: ...
    @staticmethod
    def delete(pk: int) -> None: ...


class EventMapsServiceProtocol(Protocol):
    def list_for_event(self, event_pk: int) -> list[EventMapDTO]: ...
    def read(self, *, event_pk: int, pk: int) -> EventMapDTO: ...
    def create(
        self, *, event_pk: int, data: EventMapInputDTO, image: UploadedFileProtocol
    ) -> EventMapDTO: ...
    def update(
        self,
        *,
        event_pk: int,
        pk: int,
        data: EventMapInputDTO,
        image: UploadedFileProtocol | None,
    ) -> EventMapDTO: ...
    def delete(self, *, event_pk: int, pk: int) -> None: ...
    def index(self, event_pk: int) -> MapIndexDTO: ...
