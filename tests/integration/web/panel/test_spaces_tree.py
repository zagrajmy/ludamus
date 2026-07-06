"""Integration tests for the recursive Space-tree panel CRUD."""

import json
from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import Space
from ludamus.pacts import EventDTO
from ludamus.pacts.venues import SpaceNodeDTO
from tests.integration.conftest import AgendaItemFactory, EventFactory
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


def _base_context(event, *, rooms=0):
    return {
        "current_event": EventDTO.model_validate(event),
        "events": [EventDTO.model_validate(event)],
        "is_proposal_active": False,
        "stats": {
            "hosts_count": 0,
            "pending_proposals": 0,
            "rooms_count": rooms,
            "scheduled_sessions": 0,
            "total_proposals": 0,
            "total_sessions": 0,
        },
        "active_nav": "venues",
    }


def _node(space, *, depth, is_leaf, children=None):
    return SpaceNodeDTO(
        pk=space.pk,
        event_id=space.event_id,
        parent_id=space.parent_id,
        name=space.name,
        slug=space.slug,
        capacity=space.capacity,
        description=space.description,
        order=space.order,
        depth=depth,
        is_leaf=is_leaf,
        children=children or [],
    )


def _venues_url(event):
    return reverse("panel:venues", kwargs={"slug": event.slug})


def _root(event, name="Hall", **kwargs):
    return Space.objects.create(event=event, name=name, slug=name.lower(), **kwargs)


@pytest.fixture(name="manager_client")
def manager_client_fixture(authenticated_client, active_user, sphere):
    sphere.managers.add(active_user)
    return authenticated_client


class TestSpacesTreePage:
    def test_anonymous_redirected_to_login(self, client, event):
        url = _venues_url(event)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_non_manager_redirected(self, authenticated_client, event):
        response = authenticated_client.get(_venues_url(event))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_empty_tree(self, manager_client, event):
        response = manager_client.get(_venues_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/spaces.html",
            context_data={**_base_context(event), "tree": []},
        )

    def test_renders_nested_tree(self, manager_client, event):
        root = _root(event, "Hall")
        leaf = Space.objects.create(
            event=event, parent=root, name="Room A", slug="room-a", capacity=12
        )

        response = manager_client.get(_venues_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/spaces.html",
            context_data={
                **_base_context(event, rooms=2),
                "tree": [
                    _node(
                        root,
                        depth=1,
                        is_leaf=False,
                        children=[_node(leaf, depth=2, is_leaf=True)],
                    )
                ],
            },
        )


class TestSpaceCreate:
    @staticmethod
    def _root_url(event):
        return reverse("panel:space-create", kwargs={"slug": event.slug})

    @staticmethod
    def _child_url(event, parent_pk):
        return reverse(
            "panel:space-create-child",
            kwargs={"slug": event.slug, "parent_pk": parent_pk},
        )

    def test_create_root(self, manager_client, event):
        response = manager_client.post(self._root_url(event), data={"name": "Hall"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Space created successfully.")],
            url=_venues_url(event),
        )
        created = Space.objects.get(event=event, name="Hall")
        assert created.parent_id is None

    def test_create_child(self, manager_client, event):
        root = _root(event)
        capacity = 20

        response = manager_client.post(
            self._child_url(event, root.pk),
            data={"name": "Room A", "capacity": str(capacity)},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Space created successfully.")],
            url=_venues_url(event),
        )
        child = Space.objects.get(event=event, name="Room A")
        assert child.parent_id == root.pk
        assert child.capacity == capacity

    def test_create_under_foreign_event_parent_rejected(
        self, manager_client, event, sphere
    ):
        other_event = EventFactory(sphere=sphere)
        foreign = _root(other_event, "Foreign")

        response = manager_client.post(
            self._child_url(event, foreign.pk), data={"name": "X"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Space not found.")],
            url=_venues_url(event),
        )

    def test_get_form_for_root(self, manager_client, event):
        response = manager_client.get(self._root_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/space-form.html",
            context_data={
                **_base_context(event),
                "parent": None,
                "node": None,
                "form": ANY,
            },
        )

    def test_get_child_form_foreign_parent_redirects(
        self, manager_client, event, sphere
    ):
        other_event = EventFactory(sphere=sphere)
        foreign = _root(other_event, "Foreign")

        response = manager_client.get(self._child_url(event, foreign.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Space not found.")],
            url=_venues_url(event),
        )

    def test_create_child_under_session_leaf_rerenders(self, manager_client, event):
        # A leaf already holding a session cannot become a branch; the
        # invariant surfaces as a form error and the page re-renders.
        parent = _root(event, "Hall")
        AgendaItemFactory(space=parent)

        response = manager_client.post(
            self._child_url(event, parent.pk), data={"name": "Room"}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/space-form.html",
            context_data={
                **_base_context(event, rooms=1),
                "parent": _node(parent, depth=1, is_leaf=True),
                "node": None,
                "form": ANY,
            },
        )
        assert not Space.objects.filter(name="Room").exists()


class TestSpaceEdit:
    @staticmethod
    def _url(event, pk):
        return reverse("panel:space-edit", kwargs={"slug": event.slug, "pk": pk})

    def test_edit_renames(self, manager_client, event):
        node = _root(event, "Hall")

        response = manager_client.post(
            self._url(event, node.pk), data={"name": "Grand Hall", "capacity": "5"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Space updated successfully.")],
            url=_venues_url(event),
        )
        node.refresh_from_db()
        assert node.name == "Grand Hall"
        assert node.slug == "grand-hall"

    def test_get_edit_form(self, manager_client, event):
        node = _root(event, "Hall")

        response = manager_client.get(self._url(event, node.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/space-form.html",
            context_data={
                **_base_context(event, rooms=1),
                "parent": None,
                "node": _node(node, depth=1, is_leaf=True),
                "form": ANY,
            },
        )

    def test_edit_missing_node(self, manager_client, event):
        response = manager_client.post(self._url(event, 987654), data={"name": "X"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Space not found.")],
            url=_venues_url(event),
        )

    def test_get_edit_foreign_node_redirects(self, manager_client, event, sphere):
        other_event = EventFactory(sphere=sphere)
        foreign = _root(other_event, "Foreign")

        response = manager_client.get(self._url(event, foreign.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Space not found.")],
            url=_venues_url(event),
        )

    def test_reparent_to_top_level(self, manager_client, event):
        parent = _root(event, "Hall")
        child = Space.objects.create(
            event=event, parent=parent, name="Room", slug="room", capacity=8
        )

        response = manager_client.post(
            self._url(event, child.pk),
            data={"name": "Room", "capacity": "8", "parent": ""},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Space updated successfully.")],
            url=_venues_url(event),
        )
        child.refresh_from_db()
        assert child.parent_id is None

    def test_reparent_under_another_node(self, manager_client, event):
        source = _root(event, "Hall")
        target = _root(event, "Annex")
        child = Space.objects.create(
            event=event, parent=source, name="Room", slug="room", capacity=8
        )

        response = manager_client.post(
            self._url(event, child.pk),
            data={"name": "Room", "capacity": "8", "parent": str(target.pk)},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Space updated successfully.")],
            url=_venues_url(event),
        )
        child.refresh_from_db()
        assert child.parent_id == target.pk

    def test_reparent_under_own_descendant_rejected(self, manager_client, event):
        # Moving a node under its own child would create a cycle, so the child
        # is never an offered choice; posting it is rejected and re-renders.
        root = _root(event, "Hall")
        child = Space.objects.create(event=event, parent=root, name="Room", slug="room")

        response = manager_client.post(
            self._url(event, root.pk), data={"name": "Hall", "parent": str(child.pk)}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/space-form.html",
            context_data={
                **_base_context(event, rooms=2),
                "parent": None,
                "node": _node(root, depth=1, is_leaf=False),
                "form": ANY,
            },
        )
        root.refresh_from_db()
        assert root.parent_id is None

    def test_reparent_exceeding_max_depth_rejected(self, manager_client, event):
        # The parent picker doesn't check depth, so a node at the deepest level
        # is still offered; moving another node under it would exceed the limit,
        # and the model's full_clean() raises ValidationError the view catches.
        parent = None
        for i in range(7):
            parent = Space.objects.create(
                event=event, parent=parent, name=f"L{i}", slug=f"l{i}"
            )
        deepest = parent
        node = _root(event, "Mover")

        response = manager_client.post(
            self._url(event, node.pk), data={"name": "Mover", "parent": str(deepest.pk)}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/space-form.html",
            context_data={
                **_base_context(event, rooms=8),
                "parent": None,
                "node": _node(node, depth=1, is_leaf=True),
                "form": ANY,
            },
        )
        node.refresh_from_db()
        assert node.parent_id is None

    def test_reparent_under_session_holder_rejected(self, manager_client, event):
        # A space holding a scheduled session can't become a parent, so it is
        # not an allowed target; posting it is rejected and re-renders.
        parent = _root(event, "Hall")
        child = Space.objects.create(
            event=event, parent=parent, name="Room", slug="room"
        )
        AgendaItemFactory(space=parent)

        response = manager_client.post(
            self._url(event, child.pk),
            data={"name": "Renamed", "parent": str(parent.pk)},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/space-form.html",
            context_data={
                **_base_context(event, rooms=2),
                "parent": None,
                "node": _node(child, depth=2, is_leaf=True),
                "form": ANY,
            },
        )
        child.refresh_from_db()
        assert child.name == "Room"
        assert child.parent_id == parent.pk


class TestSpaceDelete:
    @staticmethod
    def _url(event, pk):
        return reverse("panel:space-delete", kwargs={"slug": event.slug, "pk": pk})

    def test_delete_empty_subtree(self, manager_client, event):
        root = _root(event)
        Space.objects.create(event=event, parent=root, name="Room", slug="room")

        response = manager_client.post(self._url(event, root.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Space deleted successfully.")],
            url=_venues_url(event),
        )
        assert not Space.objects.filter(event=event).exists()

    def test_delete_blocked_with_sessions(self, manager_client, event):
        root = _root(event)
        leaf = Space.objects.create(event=event, parent=root, name="Room", slug="room")
        AgendaItemFactory(space=leaf)

        response = manager_client.post(self._url(event, root.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (messages.ERROR, "Cannot delete a space with scheduled sessions.")
            ],
            url=_venues_url(event),
        )
        assert Space.objects.filter(pk=root.pk).exists()

    def test_delete_missing_node(self, manager_client, event):
        response = manager_client.post(self._url(event, 987654))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Space not found.")],
            url=_venues_url(event),
        )

    def test_delete_foreign_node(self, manager_client, event, sphere):
        other_event = EventFactory(sphere=sphere)
        foreign = _root(other_event, "Foreign")

        response = manager_client.post(self._url(event, foreign.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Space not found.")],
            url=_venues_url(event),
        )
        assert Space.objects.filter(pk=foreign.pk).exists()


class TestSpaceDuplicate:
    def test_duplicate_subtree(self, manager_client, event):
        root = _root(event, "Hall")
        Space.objects.create(event=event, parent=root, name="Room", slug="room")

        response = manager_client.post(
            reverse("panel:space-duplicate", kwargs={"slug": event.slug, "pk": root.pk})
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Space duplicated successfully.")],
            url=_venues_url(event),
        )
        assert Space.objects.filter(event=event, name="Hall (Copy)").exists()

    def test_duplicate_missing_node(self, manager_client, event):
        response = manager_client.post(
            reverse("panel:space-duplicate", kwargs={"slug": event.slug, "pk": 987654})
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Space not found.")],
            url=_venues_url(event),
        )

    def test_duplicate_foreign_node(self, manager_client, event, sphere):
        other_event = EventFactory(sphere=sphere)
        foreign = _root(other_event, "Foreign")

        response = manager_client.post(
            reverse(
                "panel:space-duplicate", kwargs={"slug": event.slug, "pk": foreign.pk}
            )
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Space not found.")],
            url=_venues_url(event),
        )


class TestSpaceCopy:
    @staticmethod
    def _url(event, pk):
        return reverse("panel:space-copy", kwargs={"slug": event.slug, "pk": pk})

    def test_get_foreign_node_redirects(self, manager_client, event, sphere):
        other_event = EventFactory(sphere=sphere)
        foreign = _root(other_event, "Foreign")

        response = manager_client.get(self._url(event, foreign.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Space not found.")],
            url=_venues_url(event),
        )

    def test_get_without_other_events_warns(self, manager_client, event):
        node = _root(event, "Hall")

        response = manager_client.get(self._url(event, node.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.WARNING, "No other events available to copy to.")],
            url=_venues_url(event),
        )

    def test_post_foreign_node_redirects(self, manager_client, event, sphere):
        other_event = EventFactory(sphere=sphere)
        foreign = _root(other_event, "Foreign")

        response = manager_client.post(self._url(event, foreign.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Space not found.")],
            url=_venues_url(event),
        )

    def test_post_invalid_form_rerenders(self, manager_client, event):
        # No other events => empty choices => the target_event field is invalid.
        node = _root(event, "Hall")

        response = manager_client.post(self._url(event, node.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/space-copy.html",
            context_data={
                **_base_context(event, rooms=1),
                "node": _node(node, depth=1, is_leaf=True),
                "form": ANY,
            },
        )


class TestSpaceReorder:
    def test_reorder_roots(self, manager_client, event):
        first = _root(event, "First", order=0)
        second = _root(event, "Second", order=1)

        response = manager_client.post(
            reverse("panel:space-reorder", kwargs={"slug": event.slug}),
            data=json.dumps({"parent_pk": None, "space_ids": [second.pk, first.pk]}),
            content_type="application/json",
        )

        assert_response(response, HTTPStatus.OK)
        first.refresh_from_db()
        second.refresh_from_db()
        assert second.order == 0
        assert first.order == 1

    def _reorder(self, manager_client, event, payload):
        return manager_client.post(
            reverse("panel:space-reorder", kwargs={"slug": event.slug}),
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_reorder_ignores_foreign_event_spaces(self, manager_client, event):
        local = _root(event, "Local", order=0)
        other_event = EventFactory(sphere=event.sphere)
        foreign = Space.objects.create(
            event=other_event, name="Foreign", slug="foreign", order=1
        )

        response = self._reorder(
            manager_client,
            event,
            {"parent_pk": None, "space_ids": [foreign.pk, local.pk]},
        )

        assert_response(response, HTTPStatus.OK)
        foreign.refresh_from_db()
        local.refresh_from_db()
        assert foreign.order == 1
        assert local.order == 1

    def test_reorder_non_object_body_returns_400(self, manager_client, event):
        response = self._reorder(manager_client, event, [1, 2, 3])

        assert_response(response, HTTPStatus.BAD_REQUEST)

    def test_reorder_invalid_space_ids_returns_400(self, manager_client, event):
        response = self._reorder(
            manager_client, event, {"parent_pk": None, "space_ids": ["nope"]}
        )

        assert_response(response, HTTPStatus.BAD_REQUEST)

    def test_reorder_invalid_parent_pk_returns_400(self, manager_client, event):
        response = self._reorder(
            manager_client, event, {"parent_pk": "nope", "space_ids": []}
        )

        assert_response(response, HTTPStatus.BAD_REQUEST)

    def test_reorder_unknown_event_returns_404(self, manager_client):
        response = manager_client.post(
            reverse("panel:space-reorder", kwargs={"slug": "missing-event"}),
            data=json.dumps({"parent_pk": None, "space_ids": []}),
            content_type="application/json",
        )

        assert_response(response, HTTPStatus.NOT_FOUND)
