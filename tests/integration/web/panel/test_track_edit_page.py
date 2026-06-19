"""Integration tests for /panel/event/<slug>/tracks/<track_slug>/edit/ page."""

from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import Track
from ludamus.pacts import EventDTO, TrackDTO, UserDTO
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


class TestTrackEditPageView:
    """Tests for /panel/event/<slug>/tracks/<track_slug>/edit/ page."""

    @staticmethod
    def get_url(event, track):
        return reverse(
            "panel:track-edit", kwargs={"slug": event.slug, "track_slug": track.slug}
        )

    @staticmethod
    def make_track(event):
        return Track.objects.create(
            event=event, name="Alpha Track", slug="alpha-track", is_public=True
        )

    # GET tests

    def test_get_redirects_anonymous_user_to_login(self, client, event):
        track = self.make_track(event)
        url = self.get_url(event, track)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_get_redirects_non_manager_user(self, authenticated_client, event):
        track = self.make_track(event)

        response = authenticated_client.get(self.get_url(event, track))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_get_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        track = self.make_track(event)
        url = reverse(
            "panel:track-edit", kwargs={"slug": "nonexistent", "track_slug": track.slug}
        )

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_get_redirects_on_invalid_track_slug(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        url = reverse(
            "panel:track-edit", kwargs={"slug": event.slug, "track_slug": "nonexistent"}
        )

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Track not found.")],
            url=f"/panel/event/{event.slug}/tracks/",
        )

    def test_get_ok_for_sphere_manager(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        track = self.make_track(event)

        response = authenticated_client.get(self.get_url(event, track))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/track-edit.html",
            context_data={
                **_base_context(event),
                "track": TrackDTO.model_validate(track),
                "form": ANY,
                "spaces": [],
                "managers": [UserDTO.model_validate(active_user)],
                "selected_space_pks": [],
                "selected_manager_pks": [],
            },
        )

    # POST tests

    def test_post_redirects_anonymous_user_to_login(self, client, event):
        track = self.make_track(event)
        url = self.get_url(event, track)

        response = client.post(url, data={"name": "Updated Track"})

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_post_redirects_non_manager_user(self, authenticated_client, event):
        track = self.make_track(event)

        response = authenticated_client.post(
            self.get_url(event, track), data={"name": "Updated Track"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_post_updates_track_and_redirects(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        track = self.make_track(event)

        response = authenticated_client.post(
            self.get_url(event, track),
            data={"name": "Updated Track", "is_public": "on"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Track updated successfully.")],
            url=f"/panel/event/{event.slug}/tracks/",
        )
        track.refresh_from_db()
        assert track.name == "Updated Track"

    def test_post_drops_foreign_event_space_and_foreign_manager(
        self, authenticated_client, active_user, sphere, event
    ):
        """Spaces from another event and non-sphere managers are not attached."""
        sphere.managers.add(active_user)
        track = self.make_track(event)
        foreign_space = SpaceFactory()  # belongs to a different event
        foreign_user = UserFactory()  # not a manager of this sphere

        response = authenticated_client.post(
            self.get_url(event, track),
            data={
                "name": "Updated Track",
                "is_public": "on",
                "space_pks": [str(foreign_space.pk)],
                "manager_pks": [str(foreign_user.pk)],
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Track updated successfully.")],
            url=f"/panel/event/{event.slug}/tracks/",
        )
        track.refresh_from_db()
        assert not track.spaces.filter(pk=foreign_space.pk).exists()
        assert not track.managers.filter(pk=foreign_user.pk).exists()

    def test_post_shows_error_for_empty_name(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        track = self.make_track(event)

        response = authenticated_client.post(
            self.get_url(event, track), data={"name": ""}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/track-edit.html",
            context_data={
                **_base_context(event),
                "track": TrackDTO.model_validate(track),
                "form": ANY,
                "spaces": [],
                "managers": [UserDTO.model_validate(active_user)],
                "selected_space_pks": [],
                "selected_manager_pks": [],
            },
        )
        track.refresh_from_db()
        assert track.name == "Alpha Track"

    def test_post_redirects_on_invalid_track_slug(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        url = reverse(
            "panel:track-edit", kwargs={"slug": event.slug, "track_slug": "nonexistent"}
        )

        response = authenticated_client.post(url, data={"name": "Updated Track"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Track not found.")],
            url=f"/panel/event/{event.slug}/tracks/",
        )

    def test_post_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        track = self.make_track(event)
        url = reverse(
            "panel:track-edit", kwargs={"slug": "nonexistent", "track_slug": track.slug}
        )

        response = authenticated_client.post(url, data={"name": "Updated Track"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )
