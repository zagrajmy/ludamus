"""Tests for area delete action."""

from http import HTTPStatus

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import AgendaItem, Area, Session, Space, Venue
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


@pytest.mark.django_db
class TestAreaDeleteActionView:
    """Tests for /panel/event/<slug>/venues/<venue_slug>/areas/<area_slug>/do/delete."""

    @staticmethod
    def get_url(event, venue, area):
        return reverse(
            "panel:area-delete",
            kwargs={
                "slug": event.slug,
                "venue_slug": venue.slug,
                "area_slug": area.slug,
            },
        )

    def test_post_redirects_anonymous_user_to_login(self, client, event):
        """Anonymous users get redirect to login."""
        venue = Venue.objects.create(event=event, name="Test Venue", slug="test-venue")
        area = Area.objects.create(venue=venue, name="Test Area", slug="test-area")
        url = self.get_url(event, venue, area)

        response = client.post(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_post_redirects_non_manager_user(self, authenticated_client, event):
        """Non-managers get error message and redirect home."""
        venue = Venue.objects.create(event=event, name="Test Venue", slug="test-venue")
        area = Area.objects.create(venue=venue, name="Test Area", slug="test-area")

        response = authenticated_client.post(self.get_url(event, venue, area))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_post_deletes_area_for_sphere_manager(
        self, authenticated_client, active_user, sphere, event
    ):
        """Valid POST deletes area and redirects to venue detail."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")
        area = Area.objects.create(venue=venue, name="East Wing", slug="east-wing")
        area_pk = area.pk

        response = authenticated_client.post(self.get_url(event, venue, area))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Area deleted successfully.")],
            url=reverse(
                "panel:venue-detail",
                kwargs={"slug": event.slug, "venue_slug": venue.slug},
            ),
        )
        assert not Area.objects.filter(pk=area_pk).exists()

    def test_post_redirects_on_invalid_venue_slug(
        self, authenticated_client, active_user, sphere, event
    ):
        """Invalid venue slug triggers error message and redirect."""
        sphere.managers.add(active_user)
        url = reverse(
            "panel:area-delete",
            kwargs={
                "slug": event.slug,
                "venue_slug": "nonexistent",
                "area_slug": "test-area",
            },
        )

        response = authenticated_client.post(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Venue not found.")],
            url=reverse("panel:venues", kwargs={"slug": event.slug}),
        )

    def test_post_redirects_on_invalid_area_slug(
        self, authenticated_client, active_user, sphere, event
    ):
        """Invalid area slug triggers error message and redirect."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Test Venue", slug="test-venue")
        url = reverse(
            "panel:area-delete",
            kwargs={
                "slug": event.slug,
                "venue_slug": venue.slug,
                "area_slug": "nonexistent",
            },
        )

        response = authenticated_client.post(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Area not found.")],
            url=reverse(
                "panel:venue-detail",
                kwargs={"slug": event.slug, "venue_slug": venue.slug},
            ),
        )

    def test_get_method_not_allowed(
        self, authenticated_client, active_user, sphere, event
    ):
        """GET request returns 405 Method Not Allowed."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")
        area = Area.objects.create(venue=venue, name="East Wing", slug="east-wing")

        response = authenticated_client.get(self.get_url(event, venue, area))

        assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED

    def test_post_fails_when_area_has_sessions(
        self, authenticated_client, active_user, sphere, event
    ):
        """Cannot delete area when it has scheduled sessions."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")
        area = Area.objects.create(venue=venue, name="East Wing", slug="east-wing")
        space = Space.objects.create(area=area, name="Room 101", slug="room-101")
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

        response = authenticated_client.post(self.get_url(event, venue, area))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Cannot delete area with scheduled sessions.")],
            url=reverse(
                "panel:venue-detail",
                kwargs={"slug": event.slug, "venue_slug": venue.slug},
            ),
        )
        assert Area.objects.filter(pk=area.pk).exists()

    def test_post_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere
    ):
        """Invalid event slug triggers redirect on POST."""
        sphere.managers.add(active_user)
        url = reverse(
            "panel:area-delete",
            kwargs={
                "slug": "nonexistent",
                "venue_slug": "test-venue",
                "area_slug": "test-area",
            },
        )

        response = authenticated_client.post(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )
