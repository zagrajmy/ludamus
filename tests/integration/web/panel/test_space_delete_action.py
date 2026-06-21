"""Tests for space delete action."""

from http import HTTPStatus

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import AgendaItem, Area, Session, Space, Venue
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


@pytest.mark.django_db
class TestSpaceDeleteActionView:
    """Tests for space delete action."""

    @staticmethod
    def get_url(event, venue, area, space):
        return reverse(
            "panel:space-delete",
            kwargs={
                "slug": event.slug,
                "venue_slug": venue.slug,
                "area_slug": area.slug,
                "space_slug": space.slug,
            },
        )

    def test_post_redirects_anonymous_user_to_login(self, client, event):
        """Anonymous users get redirect to login."""
        venue = Venue.objects.create(event=event, name="Test Venue", slug="test-venue")
        area = Area.objects.create(venue=venue, name="Test Area", slug="test-area")
        space = Space.objects.create(area=area, name="Test Space", slug="test-space")
        url = self.get_url(event, venue, area, space)

        response = client.post(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_post_redirects_non_manager_user(self, authenticated_client, event):
        """Non-managers get error message and redirect home."""
        venue = Venue.objects.create(event=event, name="Test Venue", slug="test-venue")
        area = Area.objects.create(venue=venue, name="Test Area", slug="test-area")
        space = Space.objects.create(area=area, name="Test Space", slug="test-space")

        response = authenticated_client.post(self.get_url(event, venue, area, space))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_post_deletes_space_for_sphere_manager(
        self, authenticated_client, active_user, sphere, event
    ):
        """Valid POST deletes space and redirects to area detail."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")
        area = Area.objects.create(venue=venue, name="East Wing", slug="east-wing")
        space = Space.objects.create(area=area, name="Room 101", slug="room-101")
        space_pk = space.pk

        response = authenticated_client.post(self.get_url(event, venue, area, space))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Space deleted successfully.")],
            url=reverse(
                "panel:area-detail",
                kwargs={
                    "slug": event.slug,
                    "venue_slug": venue.slug,
                    "area_slug": area.slug,
                },
            ),
        )
        assert not Space.objects.filter(pk=space_pk).exists()

    def test_post_redirects_on_invalid_venue_slug(
        self, authenticated_client, active_user, sphere, event
    ):
        """Invalid venue slug triggers error message and redirect."""
        sphere.managers.add(active_user)
        url = reverse(
            "panel:space-delete",
            kwargs={
                "slug": event.slug,
                "venue_slug": "nonexistent",
                "area_slug": "test-area",
                "space_slug": "test-space",
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
            "panel:space-delete",
            kwargs={
                "slug": event.slug,
                "venue_slug": venue.slug,
                "area_slug": "nonexistent",
                "space_slug": "test-space",
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

    def test_post_redirects_on_invalid_space_slug(
        self, authenticated_client, active_user, sphere, event
    ):
        """Invalid space slug triggers error message and redirect."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Test Venue", slug="test-venue")
        area = Area.objects.create(venue=venue, name="Test Area", slug="test-area")
        url = reverse(
            "panel:space-delete",
            kwargs={
                "slug": event.slug,
                "venue_slug": venue.slug,
                "area_slug": area.slug,
                "space_slug": "nonexistent",
            },
        )

        response = authenticated_client.post(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Space not found.")],
            url=reverse(
                "panel:area-detail",
                kwargs={
                    "slug": event.slug,
                    "venue_slug": venue.slug,
                    "area_slug": area.slug,
                },
            ),
        )

    def test_get_method_not_allowed(
        self, authenticated_client, active_user, sphere, event
    ):
        """GET request returns 405 Method Not Allowed."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")
        area = Area.objects.create(venue=venue, name="East Wing", slug="east-wing")
        space = Space.objects.create(area=area, name="Room 101", slug="room-101")

        response = authenticated_client.get(self.get_url(event, venue, area, space))

        assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED

    def test_post_fails_when_space_has_sessions(
        self, authenticated_client, active_user, sphere, event
    ):
        """Cannot delete space when it has scheduled sessions."""
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

        response = authenticated_client.post(self.get_url(event, venue, area, space))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Cannot delete space with scheduled sessions.")],
            url=reverse(
                "panel:area-detail",
                kwargs={
                    "slug": event.slug,
                    "venue_slug": venue.slug,
                    "area_slug": area.slug,
                },
            ),
        )
        assert Space.objects.filter(pk=space.pk).exists()

    def test_post_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere
    ):
        """Invalid event slug triggers redirect on POST."""
        sphere.managers.add(active_user)
        url = reverse(
            "panel:space-delete",
            kwargs={
                "slug": "nonexistent",
                "venue_slug": "test-venue",
                "area_slug": "test-area",
                "space_slug": "test-space",
            },
        )

        response = authenticated_client.post(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )
