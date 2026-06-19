"""Integration tests for /panel/event/<slug>/tracks/create/ page."""

from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import Area, Space, Track, Venue
from ludamus.pacts import EventDTO, UserDTO
from tests.integration.conftest import SpaceFactory, UserFactory
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


def _base_context(event):
    return {
        "current_event": EventDTO.model_validate(event),
        "events": [EventDTO.model_validate(event)],
        "is_proposal_active": False,
        "stats": {
            "hosts_count": 0,
            "pending_proposals": 0,
            "rooms_count": 0,
            "scheduled_sessions": 0,
            "total_proposals": 0,
            "total_sessions": 0,
        },
        "active_nav": "tracks",
    }


class TestTrackCreatePageView:
    """Tests for /panel/event/<slug>/tracks/create/ page."""

    @staticmethod
    def get_url(event):
        return reverse("panel:track-create", kwargs={"slug": event.slug})

    # GET tests

    def test_get_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_get_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_get_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse("panel:track-create", kwargs={"slug": "nonexistent"})

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_get_ok_for_sphere_manager(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/track-create.html",
            context_data={
                **_base_context(event),
                "form": ANY,
                "spaces": [],
                "managers": [UserDTO.model_validate(active_user)],
                "selected_space_pks": [],
                "selected_manager_pks": [],
            },
        )

    # POST tests

    def test_post_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.post(url, data={"name": "Alpha Track"})

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_post_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.post(
            self.get_url(event), data={"name": "Alpha Track"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_post_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse("panel:track-create", kwargs={"slug": "nonexistent"})

        response = authenticated_client.post(url, data={"name": "Alpha Track"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_post_creates_track_and_redirects(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            self.get_url(event), data={"name": "Alpha Track", "is_public": "on"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Track created successfully.")],
            url=f"/panel/event/{event.slug}/tracks/",
        )
        assert Track.objects.filter(event=event, name="Alpha Track").exists()

    def test_post_creates_track_with_spaces_and_managers_atomically(
        self, authenticated_client, active_user, sphere, event
    ):
        """Spaces and managers are set in the same transaction as track creation."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Hall", slug="hall")
        area = Area.objects.create(venue=venue, name="Wing A", slug="wing-a")
        space = Space.objects.create(area=area, name="Room 1", slug="room-1")

        response = authenticated_client.post(
            self.get_url(event),
            data={
                "name": "Beta Track",
                "is_public": "on",
                "space_pks": [str(space.pk)],
                "manager_pks": [str(active_user.pk)],
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Track created successfully.")],
            url=f"/panel/event/{event.slug}/tracks/",
        )
        track = Track.objects.get(event=event, name="Beta Track")
        assert track.spaces.filter(pk=space.pk).exists()
        assert track.managers.filter(pk=active_user.pk).exists()

    def test_post_drops_foreign_event_space_and_foreign_manager(
        self, authenticated_client, active_user, sphere, event
    ):
        """Spaces from another event and non-sphere managers are not attached."""
        sphere.managers.add(active_user)
        foreign_space = SpaceFactory()  # belongs to a different event
        foreign_user = UserFactory()  # not a manager of this sphere

        response = authenticated_client.post(
            self.get_url(event),
            data={
                "name": "Gamma Track",
                "is_public": "on",
                "space_pks": [str(foreign_space.pk)],
                "manager_pks": [str(foreign_user.pk)],
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Track created successfully.")],
            url=f"/panel/event/{event.slug}/tracks/",
        )
        track = Track.objects.get(event=event, name="Gamma Track")
        assert not track.spaces.filter(pk=foreign_space.pk).exists()
        assert not track.managers.filter(pk=foreign_user.pk).exists()

    def test_post_shows_error_for_empty_name(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(self.get_url(event), data={"name": ""})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/track-create.html",
            context_data={
                **_base_context(event),
                "form": ANY,
                "spaces": [],
                "managers": [UserDTO.model_validate(active_user)],
                "selected_space_pks": [],
                "selected_manager_pks": [],
            },
        )
        assert not Track.objects.filter(event=event).exists()
