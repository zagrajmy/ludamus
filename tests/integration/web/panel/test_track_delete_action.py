"""Integration tests for /panel/event/<slug>/tracks/<track_slug>/do/delete action."""

from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import Track
from tests.integration.utils import assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_login_required,
    assert_not_a_manager,
)


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

        assert_login_required(response, url)

    def test_post_redirects_non_manager_user(self, authenticated_client, event):
        track = self.make_track(event)

        response = authenticated_client.post(self.get_url(event, track))

        assert_not_a_manager(response)

    def test_post_deletes_track_for_manager(self, panel_client, event):
        track = self.make_track(event)
        track_pk = track.pk

        response = panel_client.post(self.get_url(event, track))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Track deleted.")],
            url=f"/panel/event/{event.slug}/tracks/",
        )
        assert not Track.objects.filter(pk=track_pk).exists()

    def test_post_redirects_on_invalid_event_slug(self, panel_client, event):
        track = self.make_track(event)
        url = reverse(
            "panel:track-delete",
            kwargs={"slug": "nonexistent", "track_slug": track.slug},
        )

        response = panel_client.post(url)

        assert_event_not_found(response)

    def test_post_redirects_on_invalid_track_slug(self, panel_client, event):
        url = reverse(
            "panel:track-delete",
            kwargs={"slug": event.slug, "track_slug": "nonexistent"},
        )

        response = panel_client.post(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Track not found.")],
            url=f"/panel/event/{event.slug}/tracks/",
        )

    def test_get_not_allowed(self, panel_client, event):
        track = self.make_track(event)

        response = panel_client.get(self.get_url(event, track))

        assert_response(response, HTTPStatus.METHOD_NOT_ALLOWED)
