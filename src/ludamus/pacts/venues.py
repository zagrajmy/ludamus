"""Venue/area read-side DTOs and service protocol for print scope menus."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, field_validator


class PrintScopeOptionDTO(BaseModel):
    # A selectable print scope: any non-leaf node, labelled by its tree path.
    pk: int
    name: str


class PrintScopeDTO(BaseModel):
    # Leaf space pks to render and the scope's display name; both None for the
    # whole event.
    space_pks: frozenset[int] | None = None
    scope_name: str | None = None


class SpaceNodeDTO(BaseModel):
    # One node of the Space tree. Roots have parent_id None; capacity/description
    # are meaningful only on leaves (is_leaf). depth: root = 1.
    model_config = ConfigDict(from_attributes=True)

    pk: int
    event_id: int
    parent_id: int | None
    name: str
    slug: str
    capacity: int | None
    description: str
    location: str = ""
    order: int
    # Position in the tree, which a single Space cannot know on its own: whoever
    # walks the tree fills these in. The defaults describe a childless root.
    depth: int = 1
    is_leaf: bool = True
    track_names: list[str] = []
    children: list[SpaceNodeDTO] = []

    @field_validator("children", mode="before")
    @classmethod
    def _drop_related_manager(cls, value: object) -> object:
        # A Space has a "children" relation of its own, which building from
        # attributes would otherwise hand us instead of the nodes to render.
        return value if isinstance(value, list) else []


class SpaceInputDTO(BaseModel):
    # Editable attributes of a space, grouped so create/update take one value
    # instead of a wide parameter list. location holds structural metadata
    # (building address, room number) kept out of the free-form description.
    name: str
    capacity: int | None
    description: str = ""
    location: str = ""


class SpaceTreeRepositoryProtocol(Protocol):
    @staticmethod
    def list_tree(event_pk: int) -> list[SpaceNodeDTO]: ...
    def read(self, pk: int) -> SpaceNodeDTO: ...
    def create(
        self, *, event_id: int, parent_id: int | None, data: SpaceInputDTO
    ) -> SpaceNodeDTO: ...
    def update(
        self, *, pk: int, parent_id: int | None, data: SpaceInputDTO
    ) -> SpaceNodeDTO: ...
    @staticmethod
    def delete(pk: int) -> None: ...
    @staticmethod
    def reorder(parent_id: int | None, child_pks: list[int], event_id: int) -> None: ...
    @staticmethod
    def subtree_has_sessions(pk: int) -> bool: ...
    @staticmethod
    def space_pks_with_sessions(event_id: int) -> frozenset[int]: ...
    def duplicate(self, pk: int, new_name: str) -> SpaceNodeDTO: ...
    def copy_to_event(self, pk: int, target_event_id: int) -> SpaceNodeDTO: ...


class SpaceTreeServiceProtocol(Protocol):
    def list_tree(self, event_pk: int) -> list[SpaceNodeDTO]: ...
    def read(self, pk: int) -> SpaceNodeDTO: ...
    def create(
        self, *, event_id: int, parent_id: int | None, data: SpaceInputDTO
    ) -> SpaceNodeDTO: ...
    def update(
        self, *, pk: int, parent_id: int | None, data: SpaceInputDTO
    ) -> SpaceNodeDTO: ...
    def list_reparent_targets(
        self, *, pk: int, event_pk: int
    ) -> list[tuple[int, str]]: ...
    def reorder(
        self, *, parent_id: int | None, child_pks: list[int], event_id: int
    ) -> None: ...
    def duplicate(self, *, pk: int, new_name: str) -> SpaceNodeDTO: ...
    def copy_to_event(self, *, pk: int, target_event_id: int) -> SpaceNodeDTO: ...
    def delete_space(self, pk: int) -> bool: ...


class VenuesServiceProtocol(Protocol):
    def list_print_scopes(self, event_pk: int) -> list[PrintScopeOptionDTO]: ...
    def resolve_scope(self, event_pk: int, scope_pk: int | None) -> PrintScopeDTO: ...
