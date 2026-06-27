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
