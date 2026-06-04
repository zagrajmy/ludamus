"""Venue/area read-side DTOs and service protocol for print scope menus."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class AreaRefDTO(BaseModel):
    name: str
    slug: str


class VenueWithAreasDTO(BaseModel):
    name: str
    slug: str
    areas: list[AreaRefDTO]


class PrintScopeDTO(BaseModel):
    # Area pks to render and the scope's display name; both None for the
    # whole event.
    area_pks: frozenset[int] | None = None
    scope_name: str | None = None


class VenuesServiceProtocol(Protocol):
    def list_with_areas(self, event_pk: int) -> list[VenueWithAreasDTO]: ...
    def resolve_scope(
        self, event_pk: int, venue_slug: str | None, area_slug: str | None
    ) -> PrintScopeDTO: ...
