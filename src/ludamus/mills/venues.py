from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.pacts import NotFoundError
from ludamus.pacts.venues import (
    PrintScopeDTO,
    PrintScopeOptionDTO,
    SpaceTreeServiceProtocol,
    VenuesServiceProtocol,
)

if TYPE_CHECKING:
    from ludamus.pacts.services import TransactionProtocol
    from ludamus.pacts.venues import (
        SpaceInputDTO,
        SpaceNodeDTO,
        SpaceTreeRepositoryProtocol,
    )


def _leaf_pks(node: SpaceNodeDTO) -> list[int]:
    if node.is_leaf:
        return [node.pk]
    return [pk for child in node.children for pk in _leaf_pks(child)]


def _find_with_path(
    nodes: list[SpaceNodeDTO], pk: int, prefix: str = ""
) -> tuple[SpaceNodeDTO, str] | None:
    # Returns the node and its full tree path (same "a > b > c" format the print
    # scope picker shows), so the resolved scope_name can't collide across
    # branches that share a leaf name.
    for node in nodes:
        path = f"{prefix} > {node.name}" if prefix else node.name
        if node.pk == pk:
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

        def walk(node: SpaceNodeDTO, prefix: str) -> None:
            path = f"{prefix} > {node.name}" if prefix else node.name
            scopes.append(PrintScopeOptionDTO(pk=node.pk, name=path))
            for child in node.children:
                walk(child, path)

        for root in self._spaces.list_tree(event_pk):
            walk(root, "")
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
        self, transaction: TransactionProtocol, spaces: SpaceTreeRepositoryProtocol
    ) -> None:
        self._transaction = transaction
        self._spaces = spaces

    def list_tree(self, event_pk: int) -> list[SpaceNodeDTO]:
        return self._spaces.list_tree(event_pk)

    def read(self, pk: int) -> SpaceNodeDTO:
        return self._spaces.read(pk)

    def create(
        self, *, event_id: int, parent_id: int | None, data: SpaceInputDTO
    ) -> SpaceNodeDTO:
        return self._spaces.create(event_id=event_id, parent_id=parent_id, data=data)

    def update(
        self, *, pk: int, parent_id: int | None, data: SpaceInputDTO
    ) -> SpaceNodeDTO:
        return self._spaces.update(pk=pk, parent_id=parent_id, data=data)

    def list_reparent_targets(self, *, pk: int, event_pk: int) -> list[tuple[int, str]]:
        # Valid new parents for the node: every space in the event except the
        # node itself, its descendants (a cycle), and spaces already holding a
        # scheduled session (a leaf-with-session can't become a branch). Root is
        # offered separately by the caller as the "Top level" option.
        blocked = self._spaces.space_pks_with_sessions(event_pk)
        targets: list[tuple[int, str]] = []

        def walk(node: SpaceNodeDTO, prefix: str, *, under_self: bool) -> None:
            path = f"{prefix} > {node.name}" if prefix else node.name
            skip = under_self or node.pk == pk
            if not skip and node.pk not in blocked:
                targets.append((node.pk, path))
            for child in node.children:
                walk(child, path, under_self=skip)

        for root in self._spaces.list_tree(event_pk):
            walk(root, "", under_self=False)
        return targets

    def reorder(
        self, *, parent_id: int | None, child_pks: list[int], event_id: int
    ) -> None:
        self._spaces.reorder(parent_id, child_pks, event_id)

    def duplicate(self, *, pk: int, new_name: str) -> SpaceNodeDTO:
        return self._spaces.duplicate(pk, new_name)

    def copy_to_event(self, *, pk: int, target_event_id: int) -> SpaceNodeDTO:
        return self._spaces.copy_to_event(pk, target_event_id)

    def delete_space(self, pk: int) -> bool:
        # Leaf or branch: a subtree holding any scheduled session is undeletable;
        # otherwise the FK cascade removes the whole subtree.
        with self._transaction.atomic():
            if self._spaces.subtree_has_sessions(pk):
                return False
            self._spaces.delete(pk)
            return True
