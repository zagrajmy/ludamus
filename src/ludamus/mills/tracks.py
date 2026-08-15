from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.pacts.legacy import TrackCreateData, TrackUpdateData
from ludamus.pacts.services import DatabaseConstraintError
from ludamus.pacts.tracks import (
    DuplicateTrackNameError,
    TrackEditContextDTO,
    TrackEditFormContextDTO,
    TrackFormContextDTO,
    TrackFormData,
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
        # Submitted pks are request-supplied: keep only spaces of this event
        # and managers of this sphere, dropping cross-event/sphere tampering.
        valid_space_pks = {space.pk for space in self._spaces.list_by_event(event_pk)}
        valid_manager_pks = {
            manager.pk for manager in self._spheres.list_managers(sphere_id)
        }
        return TrackFormData(
            name=data["name"],
            is_public=data["is_public"],
            space_pks=sorted(set(data["space_pks"]) & valid_space_pks),
            manager_pks=sorted(set(data["manager_pks"]) & valid_manager_pks),
        )

    def _name_held_by_other(
        self, *, name: str, event_pk: int, track_pk: int | None
    ) -> bool:
        folded = name.casefold()
        return any(
            track.name.casefold() == folded and track.pk != track_pk
            for track in self._tracks.list_by_event(event_pk)
        )

    def create(self, *, event_pk: int, sphere_id: int, data: TrackFormData) -> None:
        with self._transaction.atomic():
            scoped = self._scoped(event_pk=event_pk, sphere_id=sphere_id, data=data)
            try:
                with self._transaction.savepoint():
                    self._tracks.create(
                        TrackCreateData(
                            event_pk=event_pk,
                            name=scoped["name"],
                            is_public=scoped["is_public"],
                            space_pks=scoped["space_pks"],
                            manager_pks=scoped["manager_pks"],
                        )
                    )
            except DatabaseConstraintError as exc:
                if self._name_held_by_other(
                    name=scoped["name"], event_pk=event_pk, track_pk=None
                ):
                    raise DuplicateTrackNameError from exc
                raise

    def update(
        self, *, event_pk: int, sphere_id: int, track_slug: str, data: TrackFormData
    ) -> None:
        with self._transaction.atomic():
            # NotFoundError from the event-scoped read surfaces to the caller,
            # so a foreign track slug 404s without side effects.
            track = self._tracks.read_by_slug(event_pk, track_slug)
            scoped = self._scoped(event_pk=event_pk, sphere_id=sphere_id, data=data)
            try:
                with self._transaction.savepoint():
                    self._tracks.update(
                        track.pk,
                        TrackUpdateData(
                            name=scoped["name"],
                            is_public=scoped["is_public"],
                            space_pks=scoped["space_pks"],
                            manager_pks=scoped["manager_pks"],
                        ),
                    )
            except DatabaseConstraintError as exc:
                if self._name_held_by_other(
                    name=scoped["name"], event_pk=event_pk, track_pk=track.pk
                ):
                    raise DuplicateTrackNameError from exc
                raise

    def delete(self, *, event_pk: int, track_slug: str) -> None:
        with self._transaction.atomic():
            track = self._tracks.read_by_slug(event_pk, track_slug)
            self._tracks.delete(track.pk)
