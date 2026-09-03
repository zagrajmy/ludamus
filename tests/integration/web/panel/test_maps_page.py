from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.contrib import messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from zeal import zeal_ignore

from ludamus.links.db.django.models import EventMap
from ludamus.pacts.maps import EventMapDTO, MapSpaceDTO
from tests.integration.conftest import PNG_BYTES, EventFactory, SpaceFactory
from tests.integration.utils import assert_login_required, assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_not_a_manager,
    panel_context,
)


def make_map(event, name, *spaces):
    event_map = EventMap.objects.create(
        event=event,
        name=name,
        image=SimpleUploadedFile("plan.png", PNG_BYTES, content_type="image/png"),
        image_original_name="plan.png",
    )
    # Fixture setup, not the code under test: each helper call writes one
    # map's spaces, which zeal reads as the same relation loaded in a loop.
    with zeal_ignore():
        event_map.spaces.set(spaces)
    return event_map


def _png(name="plan.png"):
    return SimpleUploadedFile(name, PNG_BYTES, content_type="image/png")


@pytest.mark.django_db
class TestMapsPageView:
    @staticmethod
    def _url(event):
        return reverse("panel:maps", kwargs={"slug": event.slug})

    def test_anonymous_redirected_to_login(self, client, event):
        url = self._url(event)

        response = client.get(url)

        assert_login_required(response, url)

    def test_non_manager_redirected(self, authenticated_client, event):
        response = authenticated_client.get(self._url(event))

        assert_not_a_manager(response)

    def test_lists_the_events_maps_only(self, panel_client, event):
        room = SpaceFactory(event=event, name="Room 1")
        event_map = make_map(event, "Site plan", room)
        make_map(EventFactory(), "Elsewhere")

        response = panel_client.get(self._url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/maps.html",
            context_data={
                **panel_context(event, active_nav="maps", rooms_count=1),
                "maps": [
                    EventMapDTO(
                        pk=event_map.pk,
                        event_id=event.pk,
                        name="Site plan",
                        image_url=event_map.image.url,
                        image_original_name="plan.png",
                        spaces=[
                            MapSpaceDTO(pk=room.pk, name="Room 1", has_children=False)
                        ],
                    )
                ],
            },
        )

    def test_redirects_on_invalid_event_slug(self, panel_client):
        response = panel_client.get(reverse("panel:maps", kwargs={"slug": "nope"}))

        assert_event_not_found(response)


@pytest.mark.django_db
class TestMapCreatePageView:
    @staticmethod
    def _url(event):
        return reverse("panel:map-create", kwargs={"slug": event.slug})

    def test_get_renders_the_form(self, panel_client, event):
        response = panel_client.get(self._url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/map-form.html",
            context_data={
                **panel_context(event, active_nav="maps"),
                "event_map": None,
                "form": ANY,
            },
        )

    def test_post_creates_a_map_with_its_spaces(self, panel_client, event):
        room = SpaceFactory(event=event, name="Room 1")

        response = panel_client.post(
            self._url(event),
            data={"name": "Site plan", "image": _png(), "spaces": [str(room.pk)]},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("panel:maps", kwargs={"slug": event.slug}),
            messages=[(messages.SUCCESS, "Map added.")],
        )
        event_map = EventMap.objects.get()
        assert event_map.event_id == event.pk
        assert event_map.name == "Site plan"
        assert event_map.image_original_name == "plan.png"
        assert list(event_map.spaces.all()) == [room]

    def test_post_without_an_image_keeps_the_form(self, panel_client, event):
        response = panel_client.post(self._url(event), data={"name": "Site plan"})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/map-form.html",
            context_data={
                **panel_context(event, active_nav="maps"),
                "event_map": None,
                "form": ANY,
            },
        )
        form_errors = response.context["form"].errors
        assert form_errors == {"image": ["Upload the map image."]}
        assert not EventMap.objects.exists()

    def test_post_refuses_a_space_of_another_event(self, panel_client, event):
        foreign = SpaceFactory(event=EventFactory())

        response = panel_client.post(
            self._url(event),
            data={"name": "Site plan", "image": _png(), "spaces": [str(foreign.pk)]},
        )

        # The choice list is the event's own tree, so a foreign pk never
        # validates; nothing is written either way.
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/map-form.html",
            context_data={
                **panel_context(event, active_nav="maps"),
                "event_map": None,
                "form": ANY,
            },
        )
        form_errors = response.context["form"].errors
        assert form_errors == {
            "spaces": [
                (
                    f"Select a valid choice. {foreign.pk} is not one of the"
                    " available choices."
                )
            ]
        }
        assert not EventMap.objects.exists()


@pytest.mark.django_db
class TestMapEditPageView:
    @staticmethod
    def _url(event, pk):
        return reverse("panel:map-edit", kwargs={"slug": event.slug, "pk": pk})

    def test_get_renders_the_form_with_the_map(self, panel_client, event):
        room = SpaceFactory(event=event, name="Room 1")
        event_map = make_map(event, "Site plan", room)

        response = panel_client.get(self._url(event, event_map.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/map-form.html",
            context_data={
                **panel_context(event, active_nav="maps", rooms_count=1),
                "event_map": EventMapDTO(
                    pk=event_map.pk,
                    event_id=event.pk,
                    name="Site plan",
                    image_url=event_map.image.url,
                    image_original_name="plan.png",
                    spaces=[MapSpaceDTO(pk=room.pk, name="Room 1", has_children=False)],
                ),
                "form": ANY,
            },
        )
        form_initial = response.context["form"].initial
        assert form_initial["spaces"] == [str(room.pk)]

    def test_post_keeps_the_image_when_none_is_uploaded(self, panel_client, event):
        room = SpaceFactory(event=event, name="Room 1")
        event_map = make_map(event, "Site plan", room)
        stored = event_map.image.name

        response = panel_client.post(
            self._url(event, event_map.pk), data={"name": "Renamed", "spaces": []}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("panel:maps", kwargs={"slug": event.slug}),
            messages=[(messages.SUCCESS, "Map saved.")],
        )
        event_map.refresh_from_db()
        assert event_map.name == "Renamed"
        assert event_map.image.name == stored
        assert not event_map.spaces.exists()

    def test_post_replaces_the_image(self, panel_client, event):
        event_map = make_map(event, "Site plan")
        stored = event_map.image.name

        response = panel_client.post(
            self._url(event, event_map.pk),
            data={"name": "Site plan", "image": _png("new.png")},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("panel:maps", kwargs={"slug": event.slug}),
            messages=[(messages.SUCCESS, "Map saved.")],
        )
        event_map.refresh_from_db()
        assert event_map.image.name != stored
        assert event_map.image_original_name == "new.png"

    def test_map_of_another_event_is_not_found(self, panel_client, event):
        foreign = make_map(EventFactory(), "Elsewhere")

        response = panel_client.get(self._url(event, foreign.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("panel:maps", kwargs={"slug": event.slug}),
            messages=[(messages.ERROR, "Map not found.")],
        )


@pytest.mark.django_db
class TestMapDeleteActionView:
    @staticmethod
    def _url(event, pk):
        return reverse("panel:map-delete", kwargs={"slug": event.slug, "pk": pk})

    def test_deletes_the_map(self, panel_client, event):
        event_map = make_map(event, "Site plan")

        response = panel_client.post(self._url(event, event_map.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("panel:maps", kwargs={"slug": event.slug}),
            messages=[(messages.SUCCESS, "Map deleted.")],
        )
        assert not EventMap.objects.exists()

    def test_map_of_another_event_is_left_alone(self, panel_client, event):
        foreign = make_map(EventFactory(), "Elsewhere")

        response = panel_client.post(self._url(event, foreign.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("panel:maps", kwargs={"slug": event.slug}),
            messages=[(messages.ERROR, "Map not found.")],
        )
        assert EventMap.objects.filter(pk=foreign.pk).exists()
