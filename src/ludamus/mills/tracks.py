from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.pacts.legacy import TrackCreateData, TrackUpdateData
from ludamus.pacts.tracks import (
    TrackEditContextDTO,
    TrackFormContextDTO,
    TracksPanelServiceProtocol,
)

if TYPE_CHECKING:
    from ludamus.pacts.legacy import (
        SpaceRepositoryProtocol,
        SphereRepositoryProtocol,
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

    def get_edit_context(
        self, *, event_pk: int, sphere_id: int, track_slug: str
    ) -> TrackEditContextDTO:
        track = self._tracks.read_by_slug(event_pk, track_slug)
        form_context = self.get_form_context(event_pk=event_pk, sphere_id=sphere_id)
        return TrackEditContextDTO(
            track=track,
            spaces=form_context.spaces,
            managers=form_context.managers,
            selected_space_pks=self._tracks.list_space_pks(track.pk),
            selected_manager_pks=self._tracks.list_manager_pks(track.pk),
        )

    def _scoped(
        self, *, event_pk: int, sphere_id: int, data: TrackUpdateData
    ) -> TrackUpdateData:
        # Submitted pks are request-supplied: keep only spaces of this event
        # and managers of this sphere, dropping cross-event/sphere tampering.
        valid_space_pks = {space.pk for space in self._spaces.list_by_event(event_pk)}
        valid_manager_pks = {
            manager.pk for manager in self._spheres.list_managers(sphere_id)
        }
        return TrackUpdateData(
            name=data["name"],
            is_public=data["is_public"],
            space_pks=sorted(set(data["space_pks"]) & valid_space_pks),
            manager_pks=sorted(set(data["manager_pks"]) & valid_manager_pks),
        )

    def create(self, *, event_pk: int, sphere_id: int, data: TrackUpdateData) -> None:
        with self._transaction.atomic():
            scoped = self._scoped(event_pk=event_pk, sphere_id=sphere_id, data=data)
            self._tracks.create(
                TrackCreateData(
                    event_pk=event_pk,
                    name=scoped["name"],
                    is_public=scoped["is_public"],
                    space_pks=scoped["space_pks"],
                    manager_pks=scoped["manager_pks"],
                )
            )

    def update(
        self, *, event_pk: int, sphere_id: int, track_slug: str, data: TrackUpdateData
    ) -> None:
        with self._transaction.atomic():
            # NotFoundError from the event-scoped read surfaces to the caller,
            # so a foreign track slug 404s without side effects.
            track = self._tracks.read_by_slug(event_pk, track_slug)
            scoped = self._scoped(event_pk=event_pk, sphere_id=sphere_id, data=data)
            self._tracks.update(track.pk, scoped)

    def delete(self, *, event_pk: int, track_slug: str) -> None:
        with self._transaction.atomic():
            track = self._tracks.read_by_slug(event_pk, track_slug)
            self._tracks.delete(track.pk)
