from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.pacts.legacy import TrackCreateData, TrackUpdateData
from ludamus.pacts.tracks import (
    TrackEditContextDTO,
    TrackEditFormContextDTO,
    TrackFormContextDTO,
    TrackFormData,
    TrackSelectionInvalidError,
    TracksPanelServiceProtocol,
)

if TYPE_CHECKING:
    from ludamus.pacts.legacy import (
        SpaceRepositoryProtocol,
        SphereRepositoryProtocol,
        TrackDTO,
        TrackListItemDTO,
        TrackRepositoryProtocol,
    )
    from ludamus.pacts.services import TransactionProtocol


class TracksPanelService(TracksPanelServiceProtocol):
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        tracks: TrackRepositoryProtocol,
        spaces: SpaceRepositoryProtocol,
        spheres: SphereRepositoryProtocol,
    ) -> None:
        self._transaction = transaction
        self._tracks = tracks
        self._spaces = spaces
        self._spheres = spheres

    def list_tracks(self, event_pk: int) -> list[TrackListItemDTO]:
        return self._tracks.list_by_event_with_assignments(event_pk)

    def get_form_context(self, *, event_pk: int, sphere_id: int) -> TrackFormContextDTO:
        return TrackFormContextDTO(
            spaces=self._spaces.list_by_event(event_pk),
            managers=self._spheres.list_managers(sphere_id),
        )

    def get_edit_form_context(
        self, *, event_pk: int, sphere_id: int, track_slug: str
    ) -> TrackEditFormContextDTO:
        track = self._tracks.read_by_slug(event_pk, track_slug)
        form_context = self.get_form_context(event_pk=event_pk, sphere_id=sphere_id)
        return TrackEditFormContextDTO(
            spaces=form_context.spaces, managers=form_context.managers, track=track
        )

    def get_edit_context(
        self, *, event_pk: int, sphere_id: int, track_slug: str
    ) -> TrackEditContextDTO:
        form_context = self.get_edit_form_context(
            event_pk=event_pk, sphere_id=sphere_id, track_slug=track_slug
        )
        return TrackEditContextDTO(
            spaces=form_context.spaces,
            managers=form_context.managers,
            track=form_context.track,
            selected_space_pks=self._tracks.list_space_pks(form_context.track.pk),
            selected_manager_pks=self._tracks.list_manager_pks(form_context.track.pk),
        )

    def _scoped(
        self, *, event_pk: int, sphere_id: int, data: TrackFormData
    ) -> TrackFormData:
        valid_space_pks = {space.pk for space in self._spaces.list_by_event(event_pk)}
        valid_manager_pks = {
            manager.pk for manager in self._spheres.list_managers(sphere_id)
        }
        requested_space_pks = set(data["space_pks"])
        requested_manager_pks = set(data["manager_pks"])
        if not requested_space_pks <= valid_space_pks:
            raise TrackSelectionInvalidError
        if not requested_manager_pks <= valid_manager_pks:
            raise TrackSelectionInvalidError
        return TrackFormData(
            name=data["name"],
            is_public=data["is_public"],
            space_pks=sorted(requested_space_pks),
            manager_pks=sorted(requested_manager_pks),
        )

    def create(self, *, event_pk: int, sphere_id: int, data: TrackFormData) -> TrackDTO:
        with self._transaction.atomic():
            scoped = self._scoped(event_pk=event_pk, sphere_id=sphere_id, data=data)
            return self._tracks.create(
                TrackCreateData(
                    event_pk=event_pk,
                    name=scoped["name"],
                    is_public=scoped["is_public"],
                    space_pks=scoped["space_pks"],
                    manager_pks=scoped["manager_pks"],
                )
            )

    def update(
        self, *, event_pk: int, sphere_id: int, track_slug: str, data: TrackFormData
    ) -> None:
        with self._transaction.atomic():
            track = self._tracks.read_by_slug(event_pk, track_slug)
            scoped = self._scoped(event_pk=event_pk, sphere_id=sphere_id, data=data)
            self._tracks.update(
                track.pk,
                TrackUpdateData(
                    name=scoped["name"],
                    is_public=scoped["is_public"],
                    space_pks=scoped["space_pks"],
                    manager_pks=scoped["manager_pks"],
                ),
            )

    def delete(self, *, event_pk: int, track_slug: str) -> None:
        with self._transaction.atomic():
            track = self._tracks.read_by_slug(event_pk, track_slug)
            self._tracks.delete(track.pk)
