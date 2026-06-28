import pytest

from ludamus.mills.venues import SpaceTreeService, VenuesService
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


class _ReparentRepo:
    def __init__(self, roots, with_sessions=()):
        self._roots = list(roots)
        self._with_sessions = frozenset(with_sessions)

    def list_tree(self, _event_pk):
        return list(self._roots)

    def space_pks_with_sessions(self, _event_pk):
        return self._with_sessions


def _space_tree_service(with_sessions=()):
    # Budynek A > {Parter > Sala 1, Piętro > Sala 2}; Budynek B > Hala
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
    return SpaceTreeService(None, _ReparentRepo(tree, with_sessions))


class TestListReparentTargets:
    def test_excludes_self_and_descendants(self):
        targets = _space_tree_service().list_reparent_targets(pk=10, event_pk=1)

        assert targets == [
            (1, "Budynek A"),
            (20, "Budynek A > Piętro"),
            (200, "Budynek A > Piętro > Sala 2"),
            (2, "Budynek B"),
            (30, "Budynek B > Hala"),
        ]

    def test_excludes_session_holding_spaces(self):
        targets = _space_tree_service(with_sessions={30, 200}).list_reparent_targets(
            pk=10, event_pk=1
        )

        assert targets == [
            (1, "Budynek A"),
            (20, "Budynek A > Piętro"),
            (2, "Budynek B"),
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
