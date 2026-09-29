import pytest

from ludamus.mills.venues import VenuesService
from ludamus.pacts import NotFoundError
from ludamus.pacts.venues import SpaceRecordDTO, SpaceTreeNodeDTO


def _node(*, pk, name, children=()):
    kids = list(children)
    return SpaceTreeNodeDTO(
        space=SpaceRecordDTO(
            pk=pk,
            event_id=1,
            parent_id=None,
            name=name,
            slug=name.lower(),
            capacity=None,
            description="",
            order=0,
            programme_order=0,
        ),
        is_leaf=not kids,
        no_children_reason=None,
        undeletable_reason=None,
        track_names=[],
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
            pk=1,
            name="Budynek A",
            children=[
                _node(pk=10, name="Parter", children=[_node(pk=100, name="Sala 1")]),
                _node(pk=20, name="Piętro", children=[_node(pk=200, name="Sala 2")]),
            ],
        ),
        _node(pk=2, name="Budynek B", children=[_node(pk=30, name="Hala")]),
    ]
    return VenuesService(_Tree(tree))


class TestResolveScope:
    def test_root_scope_unions_descendant_leaves(self):
        scope = _service().resolve_scope(1, 1)

        assert scope.space_pks == frozenset({100, 200})
        assert scope.scope_name == "Budynek A"

    def test_unknown_scope_raises(self):
        with pytest.raises(NotFoundError):
            _service().resolve_scope(1, 999)
