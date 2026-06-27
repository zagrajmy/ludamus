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


class SpaceNodeDTO(BaseModel):
    # One node of the Space tree. Roots have parent_id None; capacity/description
    # are meaningful only on leaves (is_leaf). depth: root = 1.
    pk: int
    event_id: int
    parent_id: int | None
    name: str
    slug: str
    capacity: int | None
    description: str
    order: int
    depth: int
    is_leaf: bool
    children: list[SpaceNodeDTO] = []


class SpaceTreeRepositoryProtocol(Protocol):
    @staticmethod
    def list_tree(event_pk: int) -> list[SpaceNodeDTO]: ...
    def read(self, pk: int) -> SpaceNodeDTO: ...
    def create(
        self,
        *,
        event_id: int,
        parent_id: int | None,
        name: str,
        capacity: int | None,
        description: str,
    ) -> SpaceNodeDTO: ...
    def update(
        self, *, pk: int, name: str, capacity: int | None, description: str
    ) -> SpaceNodeDTO: ...
    @staticmethod
    def delete(pk: int) -> None: ...
    @staticmethod
    def reorder(parent_id: int | None, child_pks: list[int]) -> None: ...
    @staticmethod
    def subtree_has_sessions(pk: int) -> bool: ...
    def duplicate(self, pk: int, new_name: str) -> SpaceNodeDTO: ...
    def copy_to_event(self, pk: int, target_event_id: int) -> SpaceNodeDTO: ...


class SpaceTreeServiceProtocol(Protocol):
    def list_tree(self, event_pk: int) -> list[SpaceNodeDTO]: ...
    def read(self, pk: int) -> SpaceNodeDTO: ...
    def create(
        self,
        *,
        event_id: int,
        parent_id: int | None,
        name: str,
        capacity: int | None,
        description: str,
    ) -> SpaceNodeDTO: ...
    def update(
        self, *, pk: int, name: str, capacity: int | None, description: str
    ) -> SpaceNodeDTO: ...
    def reorder(self, *, parent_id: int | None, child_pks: list[int]) -> None: ...
    def duplicate(self, *, pk: int, new_name: str) -> SpaceNodeDTO: ...
    def copy_to_event(self, *, pk: int, target_event_id: int) -> SpaceNodeDTO: ...
    def delete_space(self, pk: int) -> bool: ...


class VenuesServiceProtocol(Protocol):
    def list_with_areas(self, event_pk: int) -> list[VenueWithAreasDTO]: ...
    def resolve_scope(
        self, event_pk: int, venue_slug: str | None, area_slug: str | None
    ) -> PrintScopeDTO: ...
