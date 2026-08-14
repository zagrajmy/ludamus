# TODO(hasparus): Fold this module and mills/tracks.py into the event noun
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, TypedDict

if TYPE_CHECKING:
    from ludamus.pacts.crowd import UserDTO
    from ludamus.pacts.legacy import SpaceDTO, TrackDTO, TrackListItemDTO


class TrackFormData(TypedDict):
    name: str
    is_public: bool
    space_pks: list[int]
    manager_pks: list[int]


@dataclass
class TrackFormContextDTO:
    spaces: list[SpaceDTO]
    managers: list[UserDTO]


@dataclass
class TrackEditFormContextDTO(TrackFormContextDTO):
    track: TrackDTO


@dataclass
class TrackEditContextDTO(TrackEditFormContextDTO):
    selected_space_pks: list[int]
    selected_manager_pks: list[int]


class TracksPanelServiceProtocol(Protocol):
    def list_tracks(self, event_pk: int) -> list[TrackListItemDTO]: ...
    def get_form_context(
        self, *, event_pk: int, sphere_id: int
    ) -> TrackFormContextDTO: ...
    def get_edit_form_context(
        self, *, event_pk: int, sphere_id: int, track_slug: str
    ) -> TrackEditFormContextDTO: ...
    def get_edit_context(
        self, *, event_pk: int, sphere_id: int, track_slug: str
    ) -> TrackEditContextDTO: ...
    def create(
        self, *, event_pk: int, sphere_id: int, data: TrackFormData
    ) -> TrackDTO: ...
    def update(
        self, *, event_pk: int, sphere_id: int, track_slug: str, data: TrackFormData
    ) -> None: ...
    def delete(self, *, event_pk: int, track_slug: str) -> None: ...
