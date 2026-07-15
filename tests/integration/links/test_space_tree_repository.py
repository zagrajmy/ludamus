import pytest
from django.core.exceptions import ValidationError

from ludamus.adapters.db.django.models import Space, Track
from ludamus.inits.transaction import DjangoTransaction
from ludamus.links.db.django.repositories import SpaceTreeRepository
from ludamus.mills.venues import SpaceTreeService
from ludamus.pacts import NotFoundError
from ludamus.pacts.venues import SpaceInputDTO
from tests.integration.conftest import AgendaItemFactory


@pytest.fixture(name="repo")
def repo_fixture():
    return SpaceTreeRepository()


@pytest.fixture(name="service")
def service_fixture():
    return SpaceTreeService(DjangoTransaction(), SpaceTreeRepository())


def space_input(name, capacity=None, description="", location=""):
    return SpaceInputDTO(
        name=name, capacity=capacity, description=description, location=location
    )


class TestSpaceTreeRepositoryCreate:
    def test_creates_root_then_child(self, event, repo):
        capacity = 30
        root = repo.create(
            event_id=event.pk,
            parent_id=None,
            data=space_input("Main Hall", description="the big one"),
        )
        child = repo.create(
            event_id=event.pk,
            parent_id=root.pk,
            data=space_input("Room A", capacity=capacity),
        )

        assert root.parent_id is None
        assert root.depth == 1
        assert child.parent_id == root.pk
        assert child.depth == root.depth + 1
        assert child.capacity == capacity

    def test_creates_leaf_with_location(self, event, repo):
        leaf = repo.create(
            event_id=event.pk,
            parent_id=None,
            data=space_input("Room A", location="Building B, room 214"),
        )

        assert leaf.location == "Building B, room 214"
        assert repo.list_tree(event.pk)[0].location == "Building B, room 214"

    def test_same_name_under_parent_gets_unique_slug(self, event, repo):
        root = repo.create(event_id=event.pk, parent_id=None, data=space_input("Hall"))
        first = repo.create(
            event_id=event.pk, parent_id=root.pk, data=space_input("Room")
        )
        second = repo.create(
            event_id=event.pk, parent_id=root.pk, data=space_input("Room")
        )

        assert first.slug != second.slug

    def test_duplicate_root_slug_rejected(self, event, repo):
        repo.create(event_id=event.pk, parent_id=None, data=space_input("Hall"))
        duplicate = Space(event_id=event.pk, parent=None, name="Hall", slug="hall")

        with pytest.raises(ValidationError):
            duplicate.full_clean()

    def test_depth_limit_rejects_eighth_level(self, event, repo):
        parent_id = None
        for _ in range(7):  # depths 1..7 are allowed
            node = repo.create(
                event_id=event.pk, parent_id=parent_id, data=space_input("L")
            )
            parent_id = node.pk

        with pytest.raises(ValidationError):
            repo.create(event_id=event.pk, parent_id=parent_id, data=space_input("L"))

    def test_leaf_with_session_rejects_child(self, event, repo):
        leaf = repo.create(event_id=event.pk, parent_id=None, data=space_input("Room"))
        AgendaItemFactory(space=Space.objects.get(pk=leaf.pk))

        with pytest.raises(ValidationError):
            repo.create(event_id=event.pk, parent_id=leaf.pk, data=space_input("Sub"))


class TestSpaceTreeAcyclic:
    def test_self_parent_rejected(self, event, repo):
        node = repo.create(event_id=event.pk, parent_id=None, data=space_input("Room"))
        space = Space.objects.get(pk=node.pk)
        space.parent_id = space.pk

        with pytest.raises(ValidationError):
            space.full_clean()

    def test_reparent_under_own_descendant_rejected(self, event, repo):
        root = repo.create(event_id=event.pk, parent_id=None, data=space_input("Root"))
        child = repo.create(
            event_id=event.pk, parent_id=root.pk, data=space_input("Child")
        )
        root_obj = Space.objects.get(pk=root.pk)
        root_obj.parent_id = child.pk

        with pytest.raises(ValidationError):
            root_obj.full_clean()


class TestSpaceTreeRepositoryMutations:
    def test_update_rename_changes_slug(self, event, repo):
        node = repo.create(event_id=event.pk, parent_id=None, data=space_input("Room"))

        capacity = 12
        updated = repo.update(
            pk=node.pk,
            parent_id=None,
            data=space_input(
                "Lounge", capacity=capacity, description="comfy", location="floor 2"
            ),
        )

        assert updated.slug == "lounge"
        assert updated.capacity == capacity
        assert updated.description == "comfy"
        assert updated.location == "floor 2"

    def test_update_reparents_and_appends_to_new_siblings(self, event, repo):
        source = repo.create(
            event_id=event.pk, parent_id=None, data=space_input("Source")
        )
        target = repo.create(
            event_id=event.pk, parent_id=None, data=space_input("Target")
        )
        existing = repo.create(
            event_id=event.pk, parent_id=target.pk, data=space_input("Existing")
        )
        moved = repo.create(
            event_id=event.pk, parent_id=source.pk, data=space_input("Moved")
        )

        updated = repo.update(
            pk=moved.pk, parent_id=target.pk, data=space_input("Moved")
        )

        assert updated.parent_id == target.pk
        # Appended after the pre-existing child of the new parent.
        assert updated.order == Space.objects.get(pk=existing.pk).order + 1

    def test_reorder_sets_order(self, event, repo):
        root = repo.create(event_id=event.pk, parent_id=None, data=space_input("Root"))
        a = repo.create(event_id=event.pk, parent_id=root.pk, data=space_input("A"))
        b = repo.create(event_id=event.pk, parent_id=root.pk, data=space_input("B"))

        repo.reorder(root.pk, [b.pk, a.pk], event.pk)

        assert Space.objects.get(pk=b.pk).order == 0
        assert Space.objects.get(pk=a.pk).order == 1

    def test_read_unknown_raises(self, repo):
        with pytest.raises(NotFoundError):
            repo.read(987654)

    def test_list_tree_nests_and_flags_leaves(self, event, repo):
        root = repo.create(event_id=event.pk, parent_id=None, data=space_input("Root"))
        repo.create(event_id=event.pk, parent_id=root.pk, data=space_input("Leaf"))

        tree = repo.list_tree(event.pk)

        assert len(tree) == 1
        assert tree[0].is_leaf is False
        assert tree[0].depth == 1
        assert len(tree[0].children) == 1
        assert tree[0].children[0].is_leaf is True
        assert tree[0].children[0].depth == tree[0].depth + 1

    def test_list_tree_exposes_assigned_track_names(self, event, repo):
        leaf = repo.create(
            event_id=event.pk, parent_id=None, data=space_input("Room A")
        )
        track = Track.objects.create(event_id=event.pk, name="Board Games", slug="bg")
        track.spaces.add(leaf.pk)

        assert repo.list_tree(event.pk)[0].track_names == ["Board Games"]


class TestSpaceTreeServiceDelete:
    def test_delete_empty_subtree(self, event, service):
        root = service.create(
            event_id=event.pk, parent_id=None, data=space_input("Root")
        )

        assert service.delete_space(root.pk) is True
        assert not Space.objects.filter(pk=root.pk).exists()

    def test_delete_blocked_when_descendant_has_session(self, event, service):
        root = service.create(
            event_id=event.pk, parent_id=None, data=space_input("Root")
        )
        leaf = service.create(
            event_id=event.pk, parent_id=root.pk, data=space_input("Leaf")
        )
        AgendaItemFactory(space=Space.objects.get(pk=leaf.pk))

        assert service.delete_space(root.pk) is False
        assert Space.objects.filter(pk=root.pk).exists()
