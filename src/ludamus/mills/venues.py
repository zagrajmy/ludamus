from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.venues import (
    PrintScopeDTO,
    PrintScopeOptionDTO,
    SpaceInputDTO,
    SpaceTreeServiceProtocol,
    VenuesServiceProtocol,
)

if TYPE_CHECKING:
    from ludamus.pacts.event import EventRepositoryProtocol
    from ludamus.pacts.services import TransactionProtocol
    from ludamus.pacts.venues import (
        ProgrammeSpaceRowDTO,
        SpacePatch,
        SpaceRecordDTO,
        SpaceTreeNodeDTO,
        SpaceTreeRepositoryProtocol,
    )


def copy_name(name: str) -> str:
    # Bump an existing "(Copy)" / "(Copy N)" suffix instead of stacking them.
    if match := re.match(r"^(.+?) \(Copy(?: (\d+))?\)$", name):
        base = match.group(1)
        num = int(match.group(2) or 1) + 1
        return f"{base} (Copy {num})"
    return f"{name} (Copy)"


def _leaf_pks(node: SpaceTreeNodeDTO) -> list[int]:
    if node.is_leaf:
        return [node.space.pk]
    return [pk for child in node.children for pk in _leaf_pks(child)]


def _find_with_path(
    nodes: list[SpaceTreeNodeDTO], pk: int, prefix: str = ""
) -> tuple[SpaceTreeNodeDTO, str] | None:
    # Returns the node and its full tree path (same "a > b > c" format the print
    # scope picker shows), so the resolved scope_name can't collide across
    # branches that share a leaf name.
    for node in nodes:
        path = f"{prefix} > {node.space.name}" if prefix else node.space.name
        if node.space.pk == pk:
            return node, path
        if found := _find_with_path(node.children, pk, path):
            return found
    return None


class VenuesService(VenuesServiceProtocol):
    def __init__(self, spaces: SpaceTreeRepositoryProtocol) -> None:
        self._spaces = spaces

    def list_print_scopes(self, event_pk: int) -> list[PrintScopeOptionDTO]:
        # Every node is a printable scope at any level — a single room, a whole
        # floor, a building — labelled by its full tree path. resolve_scope maps
        # the chosen node to the leaf rooms beneath it (a leaf maps to itself).
        scopes: list[PrintScopeOptionDTO] = []

        def walk(node: SpaceTreeNodeDTO, ancestors: list[SpaceTreeNodeDTO]) -> None:
            lineage = [*ancestors, node]
            path = " > ".join(step.space.name for step in lineage)
            scopes.append(PrintScopeOptionDTO(pk=node.space.pk, name=path))
            for child in node.children:
                walk(child, lineage)

        for root in self._spaces.list_tree(event_pk):
            walk(root, [])
        return scopes

    def resolve_scope(self, event_pk: int, scope_pk: int | None) -> PrintScopeDTO:
        # Resolve ?scope=<pk> to the leaf pks beneath that node and a display
        # name. Raises NotFoundError on an unknown / cross-event pk.
        if scope_pk is None:
            return PrintScopeDTO()

        found = _find_with_path(self._spaces.list_tree(event_pk), scope_pk)
        if found is None:
            raise NotFoundError
        node, path = found
        return PrintScopeDTO(space_pks=frozenset(_leaf_pks(node)), scope_name=path)


class SpaceTreeService(SpaceTreeServiceProtocol):
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        spaces: SpaceTreeRepositoryProtocol,
        events: EventRepositoryProtocol,
    ) -> None:
        self._transaction = transaction
        self._spaces = spaces
        self._events = events

    def list_tree(self, event_pk: int) -> list[SpaceTreeNodeDTO]:
        return self._spaces.list_tree(event_pk)

    def list_programme_spaces(self, event_id: int) -> list[ProgrammeSpaceRowDTO]:
        return self._spaces.list_programme_spaces(event_id)

    def read(self, *, event_id: int, pk: int) -> SpaceRecordDTO:
        return self._spaces.read_in_event(event_id, pk)

    def create(
        self, *, event_id: int, parent_id: int | None, data: SpaceInputDTO
    ) -> SpaceRecordDTO:
        with self._transaction.atomic():
            if parent_id is not None:
                self._spaces.read_in_event(event_id, parent_id)
            return self._spaces.create(
                event_id=event_id, parent_id=parent_id, data=data
            )

    def patch_space(
        self, *, event_id: int, pk: int, changes: SpacePatch
    ) -> SpaceRecordDTO:
        with self._transaction.atomic():
            current = self._spaces.read_in_event(event_id, pk)
            parent_id = current.parent_id
            if "parent_id" in changes:
                new_parent = changes["parent_id"]
                parent_id = (
                    None
                    if new_parent is None
                    else self._spaces.read_in_event(event_id, new_parent).pk
                )
            return self._spaces.update(
                pk=current.pk,
                parent_id=parent_id,
                data=SpaceInputDTO(
                    name=changes.get("name", current.name),
                    capacity=changes.get("capacity", current.capacity),
                    description=changes.get("description", current.description),
                    location=changes.get("location", current.location),
                ),
            )

    def list_reparent_targets(self, *, pk: int, event_pk: int) -> list[tuple[int, str]]:
        # Valid new parents for the node: every space in the event except the
        # node itself, its descendants (a cycle), and spaces already holding a
        # scheduled session (a leaf-with-session can't become a branch). Root is
        # offered separately by the caller as the "Top level" option.
        targets: list[tuple[int, str]] = []

        def walk(node: SpaceTreeNodeDTO, ancestors: list[SpaceTreeNodeDTO]) -> None:
            lineage = [*ancestors, node]
            path = " > ".join(step.space.name for step in lineage)
            skip = any(step.space.pk == pk for step in lineage)
            if not skip and node.accepts_children:
                targets.append((node.space.pk, path))
            for child in node.children:
                walk(child, lineage)

        for root in self._spaces.list_tree(event_pk):
            walk(root, [])
        return targets

    def reorder(
        self, *, parent_id: int | None, child_pks: list[int], event_id: int
    ) -> None:
        self._spaces.reorder(parent_id, child_pks, event_id)

    def reorder_programme(self, event_id: int, space_pks: list[int]) -> None:
        with self._transaction.atomic():
            self._spaces.reorder_programme(event_id, space_pks)

    def move_to_top_level(self, event_id: int, space_pk: int) -> SpaceRecordDTO:
        with self._transaction.atomic():
            space = self._spaces.read_in_event(event_id, space_pk)
            if space.parent_id is None:
                return space
            return self._spaces.update(
                pk=space.pk,
                parent_id=None,
                data=SpaceInputDTO(
                    name=space.name,
                    capacity=space.capacity,
                    description=space.description,
                    location=space.location,
                ),
            )

    def duplicate(self, *, event_id: int, pk: int) -> SpaceRecordDTO:
        with self._transaction.atomic():
            source = self._spaces.read_in_event(event_id, pk)
            return self._spaces.duplicate(source.pk, copy_name(source.name))

    def copy_to_event(
        self, *, event_id: int, pk: int, target_event_id: int
    ) -> SpaceRecordDTO:
        with self._transaction.atomic():
            source = self._spaces.read_in_event(event_id, pk)
            target = self._events.read(target_event_id)
            if target.sphere_id != self._events.read(event_id).sphere_id:
                raise NotFoundError
            return self._spaces.copy_to_event(source.pk, target.pk)

    def delete_space(self, *, event_id: int, pk: int) -> bool:
        # Leaf or branch: a subtree holding any scheduled session is undeletable;
        # otherwise the FK cascade removes the whole subtree.
        with self._transaction.atomic():
            space = self._spaces.read_in_event(event_id, pk)
            if self._spaces.subtree_has_sessions(space.pk):
                return False
            self._spaces.delete(space.pk)
            return True
