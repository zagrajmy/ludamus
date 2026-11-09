# TODO(hasparus): Fold this module and mills/tracks.py into the event noun
# modules once PRs #719/#625/#626 land and the contested files free up.

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol, TypedDict

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ludamus.pacts.user import UserDTO
    from ludamus.pacts.venues import SpaceDTO


class TrackSelectionInvalidError(Exception):
    pass


class TrackFormData(TypedDict):
    name: str
    is_public: bool
    space_pks: list[int]
    manager_pks: list[int]


@dataclass
class TrackFormContextDTO:
    # Read aggregate for the track create form: the event/sphere-scoped
    # choices the space and manager pickers render.
    spaces: list[SpaceDTO]
    managers: list[UserDTO]


@dataclass
class TrackEditFormContextDTO(TrackFormContextDTO):
    # The create-form choices plus the track under edit: what a failed POST
    # needs to re-render the edit form (selected pks come from the submission).
    track: TrackDTO


@dataclass
class TrackEditContextDTO(TrackEditFormContextDTO):
    # The full edit-form read aggregate for the initial GET render: also the
    # currently assigned pks.
    selected_space_pks: list[int]
    selected_manager_pks: list[int]


class DuplicateTrackNameError(Exception):
    pass


@dataclass
class TrackFilterDTO:
    # The panel's track switcher: the organizer's own tracks first, and the
    # track the page is narrowed to, if any.
    tracks: list[TrackDTO]
    managed_pks: set[int]
    selected_pk: int | None


class TracksPanelServiceProtocol(Protocol):
    def list_tracks(self, event_pk: int) -> list[TrackListItemDTO]: ...
    def list_space_pks_by_event(self, event_pk: int) -> dict[int, list[int]]: ...
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
    def find_or_create(
        self, *, event_pk: int, sphere_id: int, data: TrackFormData
    ) -> TrackDTO: ...
    def update(
        self, *, event_pk: int, sphere_id: int, track_slug: str, data: TrackFormData
    ) -> None: ...
    def delete(self, *, event_pk: int, track_slug: str) -> None: ...
    def track_filter(
        self,
        *,
        event_pk: int,
        manager_id: int,
        requested_pk: int | None,
        auto_select: bool,
    ) -> TrackFilterDTO: ...


class TrackDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    creation_time: datetime
    event_id: int
    is_public: bool
    modification_time: datetime
    name: str
    pk: int
    slug: str


class TrackListItemDTO(BaseModel):
    # Track enriched with the names of its assigned spaces and managers, for the
    # panel list view. Names, not pks, so the template renders without extra IO.
    pk: int
    name: str
    slug: str
    is_public: bool
    space_names: list[str]
    manager_names: list[str]


class TrackSessionCountsDTO(BaseModel):
    # A track's sessions-per-status breakdown, plus how many accepted ones are
    # placed on the agenda. Feeds the overview progress bars without loading
    # session rows.
    pending: int = 0
    accepted: int = 0
    scheduled: int = 0
    on_hold: int = 0
    rejected: int = 0


class TrackCreateData(TypedDict):
    event_pk: int
    name: str
    is_public: bool
    space_pks: list[int]
    manager_pks: list[int]


class TrackRepositoryProtocol(Protocol):
    def create(self, data: TrackCreateData) -> TrackDTO: ...
    @staticmethod
    def get_or_create_by_slug(event_id: int, name: str, slug: str) -> int: ...
    @staticmethod
    def read(pk: int) -> TrackDTO: ...
    @staticmethod
    def find_by_event_and_name(event_pk: int, name: str) -> TrackDTO | None: ...
    @staticmethod
    def read_by_slug(event_pk: int, slug: str) -> TrackDTO: ...
    def update(self, pk: int, data: TrackFormData) -> TrackDTO: ...
    @staticmethod
    def delete(pk: int) -> None: ...
    @staticmethod
    def list_by_event(event_pk: int) -> list[TrackDTO]: ...
    @staticmethod
    def list_by_event_with_assignments(event_pk: int) -> list[TrackListItemDTO]: ...
    @staticmethod
    def list_public_by_event(event_pk: int) -> list[TrackDTO]: ...
    @staticmethod
    def list_by_manager(
        user_pk: int, event_pk: int | None = None
    ) -> list[TrackDTO]: ...
    @staticmethod
    def list_space_pks(pk: int) -> list[int]: ...
    @staticmethod
    def list_space_pks_by_event(event_pk: int) -> dict[int, list[int]]: ...
    @staticmethod
    def list_manager_pks(pk: int) -> list[int]: ...
    @staticmethod
    def list_manager_names_by_event(event_pk: int) -> dict[int, list[str]]: ...
    @staticmethod
    def list_manager_names_by_tracks(
        track_pks: Iterable[int],
    ) -> dict[int, list[str]]: ...
