import pytest

from ludamus.mills.venues import SpaceTreeService, VenuesService, copy_name
from ludamus.pacts.legacy import NotFoundError
from ludamus.pacts.venues import (
    ProgrammeSpaceRowDTO,
    SpaceInputDTO,
    SpaceRecordDTO,
    SpaceTreeNodeDTO,
)
from tests.unit.factories import FakeTransaction, event_dto

EVENT_PK = 1
SPHERE_PK = 1


def _record(
    *,
    pk,
    name,
    event_id=EVENT_PK,
    parent_id=None,
    capacity=None,
    description="",
    location="",
):
    return SpaceRecordDTO(
        pk=pk,
        event_id=event_id,
        parent_id=parent_id,
        name=name,
        slug=name.lower(),
        capacity=capacity,
        description=description,
        location=location,
        order=0,
        programme_order=0,
    )


def _node(*, pk, name, children=(), no_children_reason=None):
    kids = list(children)
    return SpaceTreeNodeDTO(
        space=_record(pk=pk, name=name),
        is_leaf=not kids,
        no_children_reason=no_children_reason,
        undeletable_reason=None,
        track_names=[],
        children=kids,
    )


class _Tree:
    def __init__(self, roots):
        self._by_event = {EVENT_PK: list(roots)}

    def list_tree(self, event_pk):
        return list(self._by_event.get(event_pk, []))


def _tree():
    # Budynek A > {Parter > Sala 1, Pietro > Sala 2}; Budynek B > Hala
    return [
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


def _service():
    return VenuesService(_Tree(_tree()))


class TestResolveScope:
    def test_root_scope_unions_descendant_leaves(self):
        scope = _service().resolve_scope(1, 1)

        assert scope.space_pks == frozenset({100, 200})
        assert scope.scope_name == "Budynek A"

    def test_nested_leaf_scope_maps_to_itself_under_its_full_path(self):
        scope = _service().resolve_scope(1, 200)

        assert scope.space_pks == frozenset({200})
        assert scope.scope_name == "Budynek A > Piętro > Sala 2"

    def test_no_scope_means_the_whole_event(self):
        scope = _service().resolve_scope(1, None)

        assert scope.space_pks is None
        assert scope.scope_name is None

    def test_unknown_scope_raises(self):
        with pytest.raises(NotFoundError):
            _service().resolve_scope(1, 999)


class TestListPrintScopes:
    def test_every_node_is_offered_under_its_tree_path_in_walk_order(self):
        scopes = _service().list_print_scopes(1)

        assert [(s.pk, s.name) for s in scopes] == [
            (1, "Budynek A"),
            (10, "Budynek A > Parter"),
            (100, "Budynek A > Parter > Sala 1"),
            (20, "Budynek A > Piętro"),
            (200, "Budynek A > Piętro > Sala 2"),
            (2, "Budynek B"),
            (30, "Budynek B > Hala"),
        ]


class FakeSpaces:
    def __init__(self, records=(), *, tree=(), with_sessions=()):
        self.records = {record.pk: record for record in records}
        self.tree = {EVENT_PK: list(tree)}
        self.with_sessions = set(with_sessions)
        self.reordered: list[tuple[int | None, list[int], int]] = []
        self.programme_orders: list[tuple[int, list[int]]] = []

    def list_tree(self, event_pk):
        return list(self.tree.get(event_pk, []))

    def list_programme_spaces(self, event_id):
        return [
            ProgrammeSpaceRowDTO(
                pk=r.pk, name=r.name, path=r.name, programme_order=0, track_names=[]
            )
            for r in self.records.values()
            if r.event_id == event_id
        ]

    def read_in_event(self, event_id, pk):
        record = self.records.get(pk)
        if record is None or record.event_id != event_id:
            raise NotFoundError
        return record

    def create(self, *, event_id, parent_id, data):
        pk = max(self.records, default=0) + 1
        self.records[pk] = _record(
            pk=pk,
            name=data.name,
            event_id=event_id,
            parent_id=parent_id,
            location=data.location,
        )
        return self.records[pk]

    def update(self, *, pk, parent_id, data):
        self.records[pk] = self.records[pk].model_copy(
            update={"parent_id": parent_id, **dict(data)}
        )
        return self.records[pk]

    def delete(self, pk):
        del self.records[pk]

    def reorder(self, parent_id, child_pks, event_id):
        self.reordered.append((parent_id, child_pks, event_id))

    def subtree_has_sessions(self, pk):
        return pk in self.with_sessions

    def reorder_programme(self, event_id, space_pks):
        self.programme_orders.append((event_id, space_pks))

    def duplicate(self, pk, new_name):
        source = self.records[pk]
        return self.create(
            event_id=source.event_id,
            parent_id=source.parent_id,
            data=SpaceInputDTO(name=new_name, capacity=None),
        )

    def copy_to_event(self, pk, target_event_id):
        source = self.records[pk]
        return self.create(
            event_id=target_event_id,
            parent_id=None,
            data=SpaceInputDTO(name=source.name, capacity=None),
        )


class FakeEvents:
    def __init__(self, sphere_by_event):
        self._sphere_by_event = sphere_by_event

    def read(self, pk):
        return event_dto(pk=pk, sphere_id=self._sphere_by_event[pk])


def _tree_service(repo, events=None):
    return SpaceTreeService(
        transaction=FakeTransaction(),
        spaces=repo,
        events=events or FakeEvents({EVENT_PK: SPHERE_PK}),
    )


class TestSpaceTreeService:
    def test_a_created_space_is_read_and_listed_in_its_event_only(self):
        repo = FakeSpaces([_record(pk=1, name="Inna", event_id=9)], tree=_tree())
        service = _tree_service(repo)

        created = service.create(
            event_id=EVENT_PK,
            parent_id=None,
            data=SpaceInputDTO(name="Sala", capacity=None, location=""),
        )

        assert service.read(event_id=EVENT_PK, pk=created.pk) == created
        assert [r.name for r in service.list_programme_spaces(EVENT_PK)] == ["Sala"]
        # NOTE: the tree is built by the repository; the service only hands
        # it on, so this line is here for the mills coverage gate alone.
        assert service.list_tree(EVENT_PK) == _tree()

    def test_read_refuses_a_space_of_another_event(self):
        repo = FakeSpaces([_record(pk=2, name="Inna", event_id=9)])

        with pytest.raises(NotFoundError):
            _tree_service(repo).read(event_id=EVENT_PK, pk=2)

    def test_creates_a_root_space(self):
        repo = FakeSpaces()

        created = _tree_service(repo).create(
            event_id=EVENT_PK,
            parent_id=None,
            data=SpaceInputDTO(name="Sala", capacity=None, location="Piętro 1"),
        )

        assert created.parent_id is None
        assert created.location == "Piętro 1"
        assert list(repo.records) == [created.pk]

    def test_creates_a_child_under_a_parent_of_the_same_event(self):
        repo = FakeSpaces([_record(pk=1, name="Budynek")])

        created = _tree_service(repo).create(
            event_id=EVENT_PK, parent_id=1, data=SpaceInputDTO(name="Sala", capacity=8)
        )

        assert created.parent_id == 1

    def test_refuses_a_parent_from_another_event(self):
        repo = FakeSpaces([_record(pk=1, name="Budynek", event_id=9)])

        with pytest.raises(NotFoundError):
            _tree_service(repo).create(
                event_id=EVENT_PK,
                parent_id=1,
                data=SpaceInputDTO(name="Sala", capacity=None),
            )

        assert list(repo.records) == [1]

    def test_patch_changes_only_the_named_fields(self):
        sala = _record(
            pk=2,
            name="Sala",
            parent_id=1,
            capacity=12,
            description="Duża",
            location="1",
        )
        repo = FakeSpaces([_record(pk=1, name="Budynek"), sala])

        patched = _tree_service(repo).patch_space(
            event_id=EVENT_PK, pk=2, changes={"name": "Sala 1"}
        )

        assert patched == sala.model_copy(update={"name": "Sala 1"})
        assert repo.records[2] == patched

    def test_patch_moves_under_a_parent_of_the_same_event_or_to_the_top(self):
        repo = FakeSpaces(
            [
                _record(pk=1, name="A"),
                _record(pk=3, name="B"),
                _record(pk=2, name="Sala", parent_id=1),
            ]
        )
        service = _tree_service(repo)
        other_parent = 3

        assert (
            service.patch_space(
                event_id=EVENT_PK, pk=2, changes={"parent_id": other_parent}
            )
        ).parent_id == other_parent
        assert (
            service.patch_space(event_id=EVENT_PK, pk=2, changes={"parent_id": None})
        ).parent_id is None

    def test_patch_refuses_a_space_of_another_event(self):
        foreign = _record(pk=2, name="Sala", event_id=9)
        repo = FakeSpaces([foreign])

        with pytest.raises(NotFoundError):
            _tree_service(repo).patch_space(
                event_id=EVENT_PK, pk=2, changes={"name": "Mine"}
            )

        assert repo.records[2] == foreign

    def test_patch_refuses_a_parent_of_another_event(self):
        sala = _record(pk=2, name="Sala")
        repo = FakeSpaces([_record(pk=1, name="Obcy", event_id=9), sala])

        with pytest.raises(NotFoundError):
            _tree_service(repo).patch_space(
                event_id=EVENT_PK, pk=2, changes={"parent_id": 1}
            )

        assert repo.records[2] == sala

    def test_reparent_targets_skip_self_descendants_and_full_leaves(self):
        tree = [
            _node(
                pk=1,
                name="Budynek A",
                children=[
                    _node(pk=10, name="Parter", children=[_node(pk=100, name="S1")]),
                    _node(pk=20, name="Piętro", no_children_reason="holds sessions"),
                ],
            ),
            _node(pk=2, name="Budynek B"),
        ]

        targets = _tree_service(FakeSpaces(tree=tree)).list_reparent_targets(
            pk=10, event_pk=EVENT_PK
        )

        assert targets == [(1, "Budynek A"), (2, "Budynek B")]

    def test_reparent_targets_are_named_by_their_tree_path(self):
        targets = _tree_service(FakeSpaces(tree=_tree())).list_reparent_targets(
            pk=200, event_pk=EVENT_PK
        )

        assert targets == [
            (1, "Budynek A"),
            (10, "Budynek A > Parter"),
            (100, "Budynek A > Parter > Sala 1"),
            (20, "Budynek A > Piętro"),
            (2, "Budynek B"),
            (30, "Budynek B > Hala"),
        ]

    def test_reorder_hands_the_sibling_order_to_the_repository(self):
        repo = FakeSpaces()

        _tree_service(repo).reorder(parent_id=1, child_pks=[3, 2], event_id=EVENT_PK)

        assert repo.reordered == [(1, [3, 2], EVENT_PK)]

    def test_reorder_programme_stores_the_new_order(self):
        repo = FakeSpaces()

        _tree_service(repo).reorder_programme(EVENT_PK, [200, 100])

        assert repo.programme_orders == [(EVENT_PK, [200, 100])]

    def test_move_to_top_level_detaches_a_nested_space(self):
        nested = _record(
            pk=2,
            name="Sala",
            parent_id=1,
            capacity=12,
            description="Duża sala",
            location="Piętro 1",
        )
        repo = FakeSpaces([_record(pk=1, name="Budynek"), nested])

        moved = _tree_service(repo).move_to_top_level(EVENT_PK, 2)

        assert moved == nested.model_copy(update={"parent_id": None})
        assert repo.records[2] == moved

    def test_move_to_top_level_of_a_root_changes_nothing(self):
        repo = FakeSpaces([_record(pk=1, name="Budynek")])

        assert _tree_service(repo).move_to_top_level(EVENT_PK, 1) == repo.records[1]

    def test_move_to_top_level_refuses_a_space_of_another_event(self):
        foreign = _record(pk=1, name="Sala", event_id=9, parent_id=5)
        repo = FakeSpaces([foreign])

        with pytest.raises(NotFoundError):
            _tree_service(repo).move_to_top_level(EVENT_PK, 1)

        assert repo.records[1] == foreign

    def test_duplicate_adds_a_sibling_under_the_new_name(self):
        repo = FakeSpaces([_record(pk=1, name="Sala", parent_id=7)])

        copy = _tree_service(repo).duplicate(event_id=EVENT_PK, pk=1)

        assert (copy.name, copy.parent_id) == ("Sala (Copy)", 7)
        assert set(repo.records) == {1, copy.pk}

    def test_duplicate_refuses_a_space_of_another_event(self):
        repo = FakeSpaces([_record(pk=1, name="Sala", event_id=9)])

        with pytest.raises(NotFoundError):
            _tree_service(repo).duplicate(event_id=EVENT_PK, pk=1)

        assert list(repo.records) == [1]

    def test_copy_to_event_lands_as_a_root_of_the_target(self):
        repo = FakeSpaces([_record(pk=1, name="Sala", parent_id=7)])
        events = FakeEvents({EVENT_PK: SPHERE_PK, 9: SPHERE_PK})

        copy = _tree_service(repo, events).copy_to_event(
            event_id=EVENT_PK, pk=1, target_event_id=9
        )

        assert (copy.event_id, copy.parent_id, copy.name) == (9, None, "Sala")

    def test_copy_to_event_refuses_a_space_of_another_event(self):
        repo = FakeSpaces([_record(pk=1, name="Sala", event_id=8)])
        events = FakeEvents({EVENT_PK: SPHERE_PK, 8: SPHERE_PK, 9: SPHERE_PK})

        with pytest.raises(NotFoundError):
            _tree_service(repo, events).copy_to_event(
                event_id=EVENT_PK, pk=1, target_event_id=9
            )

        assert list(repo.records) == [1]

    def test_copy_to_event_refuses_a_target_in_another_sphere(self):
        repo = FakeSpaces([_record(pk=1, name="Sala")])
        events = FakeEvents({EVENT_PK: SPHERE_PK, 9: SPHERE_PK + 1})

        with pytest.raises(NotFoundError):
            _tree_service(repo, events).copy_to_event(
                event_id=EVENT_PK, pk=1, target_event_id=9
            )

        assert list(repo.records) == [1]

    def test_delete_removes_a_subtree_without_sessions(self):
        repo = FakeSpaces([_record(pk=1, name="Sala")])

        assert _tree_service(repo).delete_space(event_id=EVENT_PK, pk=1)
        assert not repo.records

    def test_delete_refuses_a_subtree_holding_a_session(self):
        repo = FakeSpaces([_record(pk=1, name="Sala")], with_sessions=[1])

        assert not _tree_service(repo).delete_space(event_id=EVENT_PK, pk=1)
        assert list(repo.records) == [1]

    def test_delete_refuses_a_space_of_another_event(self):
        repo = FakeSpaces([_record(pk=1, name="Sala", event_id=9)])

        with pytest.raises(NotFoundError):
            _tree_service(repo).delete_space(event_id=EVENT_PK, pk=1)

        assert list(repo.records) == [1]


class TestCopyName:
    def test_names_a_first_copy(self):
        assert copy_name("Main Hall") == "Main Hall (Copy)"

    def test_increments_copy_suffix(self):
        assert copy_name("Main Hall (Copy)") == "Main Hall (Copy 2)"

    def test_increments_high_numbered_copy_suffix(self):
        assert copy_name("Main Hall (Copy 99)") == "Main Hall (Copy 100)"

    @pytest.mark.parametrize(
        ("name", "expected"),
        (
            ("Room (A)", "Room (A) (Copy)"),
            ("Room (Copy) Extra", "Room (Copy) Extra (Copy)"),
            ("(Copy)", "(Copy) (Copy)"),
        ),
    )
    def test_leaves_parentheses_that_are_not_a_copy_suffix(self, name, expected):
        assert copy_name(name) == expected
