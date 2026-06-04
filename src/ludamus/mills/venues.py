"""Venue/area read-side service backing the print scope menus."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.pacts.printing import AreaRefDTO, PrintScopeDTO, VenueWithAreasDTO

if TYPE_CHECKING:
    from ludamus.pacts import AreaRepositoryProtocol, VenueRepositoryProtocol


class VenuesService:
    def __init__(
        self, venues: VenueRepositoryProtocol, areas: AreaRepositoryProtocol
    ) -> None:
        self._venues = venues
        self._areas = areas

    def list_with_areas(self, event_pk: int) -> list[VenueWithAreasDTO]:
        return [
            VenueWithAreasDTO(
                name=venue.name,
                slug=venue.slug,
                areas=[
                    AreaRefDTO(name=area.name, slug=area.slug)
                    for area in self._areas.list_by_venue(venue.pk)
                ],
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
