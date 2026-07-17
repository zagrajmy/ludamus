"""Integration tests for /panel/event/<slug>/tracks/<track_slug>/do/delete action."""

from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import Track
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


class TestTrackDeleteActionView:
    """Tests for /panel/event/<slug>/tracks/<track_slug>/do/delete action."""

    @staticmethod
    def get_url(event, track):
        return reverse(
            "panel:track-delete", kwargs={"slug": event.slug, "track_slug": track.slug}
        )

    @staticmethod
    def make_track(event):
        return Track.objects.create(
            event=event, name="Alpha Track", slug="alpha-track", is_public=True
        )

    def test_post_redirects_anonymous_user_to_login(self, client, event):
        track = self.make_track(event)
        url = self.get_url(event, track)

        response = client.post(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_post_redirects_non_manager_user(self, authenticated_client, event):
        track = self.make_track(event)

        response = authenticated_client.post(self.get_url(event, track))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_post_deletes_track_for_manager(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        track = self.make_track(event)
        track_pk = track.pk

        response = authenticated_client.post(self.get_url(event, track))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Track deleted.")],
            url=f"/panel/event/{event.slug}/tracks/",
        )
        assert not Track.objects.filter(pk=track_pk).exists()

    def test_post_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        track = self.make_track(event)
        url = reverse(
            "panel:track-delete",
            kwargs={"slug": "nonexistent", "track_slug": track.slug},
        )

        response = authenticated_client.post(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_post_redirects_on_invalid_track_slug(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        url = reverse(
            "panel:track-delete",
            kwargs={"slug": event.slug, "track_slug": "nonexistent"},
        )

        response = authenticated_client.post(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Track not found.")],
            url=f"/panel/event/{event.slug}/tracks/",
        )

    def test_get_not_allowed(self, authenticated_client, active_user, sphere, event):
        sphere.managers.add(active_user)
        track = self.make_track(event)

        response = authenticated_client.get(self.get_url(event, track))

        assert_response(response, HTTPStatus.METHOD_NOT_ALLOWED)
