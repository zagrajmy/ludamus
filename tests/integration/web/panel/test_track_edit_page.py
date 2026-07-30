"""Integration tests for /panel/event/<slug>/tracks/<track_slug>/edit/ page."""

from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import Track
from ludamus.pacts import TrackDTO
from ludamus.pacts.crowd import UserDTO
from tests.integration.conftest import SpaceFactory, UserFactory
from tests.integration.utils import assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_login_required,
    assert_not_a_manager,
    panel_context,
)


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

        assert_login_required(response, url)

    def test_get_redirects_non_manager_user(self, authenticated_client, event):
        track = self.make_track(event)

        response = authenticated_client.get(self.get_url(event, track))

        assert_not_a_manager(response)

    def test_get_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        track = self.make_track(event)
        url = reverse(
            "panel:track-edit", kwargs={"slug": "nonexistent", "track_slug": track.slug}
        )

        response = authenticated_client.get(url)

        assert_event_not_found(response)

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
                **panel_context(event, active_nav="tracks"),
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

        assert_login_required(response, url)

    def test_post_redirects_non_manager_user(self, authenticated_client, event):
        track = self.make_track(event)

        response = authenticated_client.post(
            self.get_url(event, track), data={"name": "Updated Track"}
        )

        assert_not_a_manager(response)

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
                **panel_context(event, active_nav="tracks"),
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

        assert_event_not_found(response)
