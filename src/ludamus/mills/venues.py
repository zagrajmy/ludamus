"""Venue/area read-side service backing the print scope menus."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from ludamus.pacts.venues import AreaRefDTO, PrintScopeDTO, VenueWithAreasDTO

if TYPE_CHECKING:
    from ludamus.pacts import AreaRepositoryProtocol, VenueRepositoryProtocol
    from ludamus.pacts.services import TransactionProtocol
    from ludamus.pacts.venues import SpaceNodeDTO, SpaceTreeRepositoryProtocol


class VenuesService:
    def __init__(
        self, venues: VenueRepositoryProtocol, areas: AreaRepositoryProtocol
    ) -> None:
        self._venues = venues
        self._areas = areas

    def list_with_areas(self, event_pk: int) -> list[VenueWithAreasDTO]:
        areas_by_venue: dict[int, list[AreaRefDTO]] = defaultdict(list)
        for area in self._areas.list_by_event(event_pk):
            areas_by_venue[area.venue_id].append(
                AreaRefDTO(name=area.name, slug=area.slug)
            )
        return [
            VenueWithAreasDTO(
                name=venue.name, slug=venue.slug, areas=areas_by_venue.get(venue.pk, [])
            )
            for venue in self._venues.list_by_event(event_pk)
        ]

    def resolve_scope(
        self, event_pk: int, venue_slug: str | None, area_slug: str | None
    ) -> PrintScopeDTO:
        # Resolve ?venue=/&area= slugs to the area pks to render and a display
        # name. Raises NotFoundError on an unknown slug.
        if not venue_slug:
            return PrintScopeDTO()

        venue = self._venues.read_by_slug(event_pk, venue_slug)
        if not area_slug:
            area_pks = frozenset(
                area.pk for area in self._areas.list_by_venue(venue.pk)
            )
            return PrintScopeDTO(area_pks=area_pks, scope_name=venue.name)

        area = self._areas.read_by_slug(venue.pk, area_slug)
        return PrintScopeDTO(area_pks=frozenset({area.pk}), scope_name=area.name)


class SpaceTreeService:
    def __init__(
        self, transaction: TransactionProtocol, spaces: SpaceTreeRepositoryProtocol
    ) -> None:
        self._transaction = transaction
        self._spaces = spaces

    def list_tree(self, event_pk: int) -> list[SpaceNodeDTO]:
        return self._spaces.list_tree(event_pk)

    def create(
        self,
        *,
        event_id: int,
        parent_id: int | None,
        name: str,
        capacity: int | None,
        description: str,
    ) -> SpaceNodeDTO:
        return self._spaces.create(
            event_id=event_id,
            parent_id=parent_id,
            name=name,
            capacity=capacity,
            description=description,
        )

    def update(
        self, *, pk: int, name: str, capacity: int | None, description: str
    ) -> SpaceNodeDTO:
        return self._spaces.update(
            pk=pk, name=name, capacity=capacity, description=description
        )

    def reorder(self, *, parent_id: int | None, child_pks: list[int]) -> None:
        self._spaces.reorder(parent_id, child_pks)

    def delete_space(self, pk: int) -> bool:
        # Leaf or branch: a subtree holding any scheduled session is undeletable;
        # otherwise the FK cascade removes the whole subtree.
        with self._transaction.atomic():
            if self._spaces.subtree_has_sessions(pk):
                return False
            self._spaces.delete(pk)
            return True
