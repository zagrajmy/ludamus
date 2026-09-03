"""Event maps: uploaded venue plans and the spaces each one shows."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from ludamus.pacts.legacy import UploadedFileProtocol


class MapSpaceDTO(BaseModel):
    # A space attached to a map, flat: the pk the schedule keys on and the
    # tree path a reader recognises it by.
    pk: int
    name: str


class MapTreeNodeDTO(BaseModel):
    # The attached spaces as the page draws them — a file tree. An ancestor
    # that is not attached itself is still a node, so the reader sees where a
    # room sits, but only an attached node links to the schedule. A group is
    # filtered as a venue, a room as itself.
    pk: int
    name: str
    attached: bool
    has_children: bool
    children: list[MapTreeNodeDTO]


class EventMapDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pk: int
    event_id: int
    name: str
    image_url: str
    image_original_name: str = ""
    spaces: list[MapSpaceDTO] = []
    tree: list[MapTreeNodeDTO] = []

    @property
    def space_pks(self) -> list[int]:
        return [space.pk for space in self.spaces]


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
        self, *, event_pk: int, name: str, image: UploadedFileProtocol
    ) -> EventMapDTO: ...
    def update(
        self, *, pk: int, name: str, image: UploadedFileProtocol | None
    ) -> EventMapDTO: ...
    @staticmethod
    def set_spaces(pk: int, space_pks: list[int]) -> None: ...
    @staticmethod
    def delete(pk: int) -> None: ...


class EventMapsServiceProtocol(Protocol):
    def list_for_event(self, event_pk: int) -> list[EventMapDTO]: ...
    def read(self, *, event_pk: int, pk: int) -> EventMapDTO: ...
    def create(
        self, *, event_pk: int, name: str, image: UploadedFileProtocol
    ) -> EventMapDTO: ...
    def update(
        self, *, event_pk: int, pk: int, name: str, image: UploadedFileProtocol | None
    ) -> EventMapDTO: ...
    def attach_spaces(
        self, *, event_pk: int, pk: int, space_pks: list[int]
    ) -> None: ...
    def delete(self, *, event_pk: int, pk: int) -> None: ...
    def index(self, event_pk: int) -> MapIndexDTO: ...
