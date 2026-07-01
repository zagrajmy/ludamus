from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ludamus.adapters.db.django.repositories import DjangoSpaceRepository

if TYPE_CHECKING:
    from ludamus.adapters.db.django.models import Event, Space


@pytest.fixture
def repo() -> DjangoSpaceRepository:
    return DjangoSpaceRepository()


@pytest.mark.django_db
class TestDjangoSpaceRepositoryTree:
    def test_get_tree_for_event_returns_top_level_nodes(
        self, repo: DjangoSpaceRepository, space_factory: callable, event: Event
    ) -> None:
        space_factory(name="Root A", slug="root-a")
        space_factory(name="Root B", slug="root-b")

        tree = repo.get_tree_for_event(event_id=event.pk)

        assert len(tree) == 2
        assert {node.name for node in tree} == {"Root A", "Root B"}

    def test_get_tree_for_event_nests_children(
        self, repo: DjangoSpaceRepository, space_factory: callable, event: Event
    ) -> None:
        parent = space_factory(name="Building", slug="building")
        space_factory(name="Room", slug="room", parent=parent)

        tree = repo.get_tree_for_event(event_id=event.pk)

        assert len(tree) == 1
        assert tree[0].name == "Building"
        assert len(tree[0].children) == 1
        assert tree[0].children[0].name == "Room"

    def test_get_tree_for_event_nests_deeply(
        self, repo: DjangoSpaceRepository, space_factory: callable, event: Event
    ) -> None:
        building = space_factory(name="Building", slug="building")
        floor = space_factory(name="Floor", slug="floor", parent=building)
        space_factory(name="Room", slug="room", parent=floor, capacity=10)

        tree = repo.get_tree_for_event(event_id=event.pk)

        assert tree[0].children[0].children[0].name == "Room"
        assert tree[0].children[0].children[0].capacity == 10

    def test_get_tree_for_event_empty_when_no_spaces(
        self, repo: DjangoSpaceRepository, event: Event
    ) -> None:
        tree = repo.get_tree_for_event(event_id=event.pk)

        assert tree == []

    def test_get_tree_for_event_orders_by_position(
        self, repo: DjangoSpaceRepository, space_factory: callable, event: Event
    ) -> None:
        from ludamus.adapters.db.django.models import Space

        second = space_factory(name="Second", slug="second")
        first = space_factory(name="First", slug="first")
        Space.objects.filter(pk=first.pk).update(position=0)
        Space.objects.filter(pk=second.pk).update(position=1)

        tree = repo.get_tree_for_event(event_id=event.pk)

        assert [node.name for node in tree] == ["First", "Second"]
