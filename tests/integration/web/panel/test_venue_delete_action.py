"""Integration tests for /panel/event/<slug>/venues/<venue_slug>/do/delete action."""

from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import AgendaItem, Area, Session, Space, Venue
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


class TestVenueDeleteActionView:
    """Tests for /panel/event/<slug>/venues/<venue_slug>/do/delete action."""

    @staticmethod
    def get_url(event, venue):
        return reverse(
            "panel:venue-delete", kwargs={"slug": event.slug, "venue_slug": venue.slug}
        )

    def test_post_redirects_anonymous_user_to_login(self, client, event):
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")
        url = self.get_url(event, venue)

        response = client.post(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_post_redirects_non_manager_user(self, authenticated_client, event):
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")

        response = authenticated_client.post(self.get_url(event, venue))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_post_deletes_venue_for_manager(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")
        venue_pk = venue.pk

        response = authenticated_client.post(self.get_url(event, venue))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Venue deleted successfully.")],
            url=f"/panel/event/{event.slug}/venues/",
        )
        assert not Venue.objects.filter(pk=venue_pk).exists()

    def test_post_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")
        url = reverse(
            "panel:venue-delete",
            kwargs={"slug": "nonexistent", "venue_slug": venue.slug},
        )

        response = authenticated_client.post(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_post_redirects_on_invalid_venue_slug(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        url = reverse(
            "panel:venue-delete",
            kwargs={"slug": event.slug, "venue_slug": "nonexistent"},
        )

        response = authenticated_client.post(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Venue not found.")],
            url=f"/panel/event/{event.slug}/venues/",
        )

    def test_get_not_allowed(self, authenticated_client, active_user, sphere, event):
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")

        response = authenticated_client.get(self.get_url(event, venue))

        assert_response(response, HTTPStatus.METHOD_NOT_ALLOWED)

    def test_post_fails_when_venue_has_sessions(
        self, authenticated_client, active_user, sphere, event
    ):
        """Cannot delete venue when it has scheduled sessions."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")
        area = Area.objects.create(venue=venue, name="Test Area", slug="test-area")
        space = Space.objects.create(
            area=area, name="Test Space", slug="test-space", event=area.venue.event
        )
        session = Session.objects.create(
            event=event,
            title="Test Session",
            slug="test-session",
            display_name="Test Host",
            participants_limit=10,
        )
        AgendaItem.objects.create(
            session=session,
            space=space,
            start_time=event.start_time,
            end_time=event.end_time,
        )

        response = authenticated_client.post(self.get_url(event, venue))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Cannot delete venue with scheduled sessions.")],
            url=f"/panel/event/{event.slug}/venues/",
        )
        assert Venue.objects.filter(pk=venue.pk).exists()
