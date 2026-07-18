"""Integration tests for /panel/event/<slug>/tracks/ page."""

from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import Space, Track
from ludamus.pacts import EventDTO, TrackListItemDTO
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
        "active_nav": "tracks",
    }


class TestTracksPageView:
    """Tests for /panel/event/<slug>/tracks/ page."""

    @staticmethod
    def get_url(event):
        return reverse("panel:tracks", kwargs={"slug": event.slug})

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
        url = reverse("panel:tracks", kwargs={"slug": "nonexistent"})

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_get_ok_empty(self, authenticated_client, active_user, sphere, event):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/tracks.html",
            context_data={**_base_context(event), "tracks": []},
        )

    def test_get_shows_tracks_in_context(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        track = Track.objects.create(
            event=event, name="Morning Track", slug="morning-track", is_public=True
        )

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/tracks.html",
            context_data={
                **_base_context(event),
                "tracks": [
                    TrackListItemDTO(
                        pk=track.pk,
                        name="Morning Track",
                        slug="morning-track",
                        is_public=True,
                        space_names=[],
                        manager_names=[],
                    )
                ],
            },
        )

    def test_get_shows_assigned_spaces_and_managers(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        track = Track.objects.create(
            event=event, name="Morning Track", slug="morning-track", is_public=True
        )
        space = Space.objects.create(event=event, name="Room A", slug="room-a")
        track.spaces.add(space)
        track.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/tracks.html",
            context_data={
                **_base_context(event, rooms=1),
                "tracks": [
                    TrackListItemDTO(
                        pk=track.pk,
                        name="Morning Track",
                        slug="morning-track",
                        is_public=True,
                        space_names=["Room A"],
                        manager_names=[active_user.name],
                    )
                ],
            },
        )
