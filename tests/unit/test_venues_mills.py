import pytest

from ludamus.mills.venues import VenuesService
from ludamus.pacts import NotFoundError
from ludamus.pacts.venues import SpaceNodeDTO


def _node(pk, name, children=()):
    kids = list(children)
    return SpaceNodeDTO(
        pk=pk,
        event_id=1,
        parent_id=None,
        name=name,
        slug=name.lower(),
        capacity=None,
        description="",
        order=0,
        depth=1,
        is_leaf=not kids,
        children=kids,
    )


class _Tree:
    def __init__(self, roots):
        self._roots = list(roots)

    def list_tree(self, _event_pk):
        return list(self._roots)


def _service():
    # Budynek A > {Parter > Sala 1, Pietro > Sala 2}; Budynek B > Hala
    tree = [
        _node(
            1,
            "Budynek A",
            children=[
                _node(10, "Parter", children=[_node(100, "Sala 1")]),
                _node(20, "Piętro", children=[_node(200, "Sala 2")]),
            ],
        ),
        _node(2, "Budynek B", children=[_node(30, "Hala")]),
    ]
    return VenuesService(_Tree(tree))


class TestListPrintScopes:
    def test_lists_every_node_with_paths(self):
        result = _service().list_print_scopes(1)

        assert [(s.pk, s.name) for s in result] == [
            (1, "Budynek A"),
            (10, "Budynek A > Parter"),
            (100, "Budynek A > Parter > Sala 1"),
            (20, "Budynek A > Piętro"),
            (200, "Budynek A > Piętro > Sala 2"),
            (2, "Budynek B"),
            (30, "Budynek B > Hala"),
        ]


class TestResolveScope:
    def test_no_scope_is_whole_event(self):
        scope = _service().resolve_scope(1, None)

        assert scope.space_pks is None
        assert scope.scope_name is None

    def test_root_scope_unions_descendant_leaves(self):
        scope = _service().resolve_scope(1, 1)

        assert scope.space_pks == frozenset({100, 200})
        assert scope.scope_name == "Budynek A"

    def test_mid_scope_is_its_leaves(self):
        scope = _service().resolve_scope(1, 10)

        assert scope.space_pks == frozenset({100})
        assert scope.scope_name == "Budynek A > Parter"

    def test_unknown_scope_raises(self):
        with pytest.raises(NotFoundError):
            _service().resolve_scope(1, 999)
