"""Tests for space reorder action."""

import json
from http import HTTPStatus

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import Area, Space, Venue
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


@pytest.mark.django_db
class TestSpaceReorderActionView:
    """Tests for space reorder action."""

    @staticmethod
    def get_url(event, venue, area):
        return reverse(
            "panel:space-reorder",
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

        response = client.post(
            url, json.dumps({"space_ids": []}), content_type="application/json"
        )

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_post_error_for_non_manager_user(self, authenticated_client, event):
        """Non-managers get error."""
        venue = Venue.objects.create(event=event, name="Test Venue", slug="test-venue")
        area = Area.objects.create(venue=venue, name="Test Area", slug="test-area")

        response = authenticated_client.post(
            self.get_url(event, venue, area),
            json.dumps({"space_ids": []}),
            content_type="application/json",
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_post_reorders_spaces_for_sphere_manager(
        self, authenticated_client, active_user, sphere, event
    ):
        """Valid POST reorders spaces and returns success."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")
        area = Area.objects.create(venue=venue, name="East Wing", slug="east-wing")
        space1 = Space.objects.create(
            area=area, name="Space 1", slug="space-1", order=0, event=area.venue.event
        )
        space2 = Space.objects.create(
            area=area, name="Space 2", slug="space-2", order=1, event=area.venue.event
        )
        space3 = Space.objects.create(
            area=area, name="Space 3", slug="space-3", order=2, event=area.venue.event
        )

        # Reorder: 3, 1, 2
        response = authenticated_client.post(
            self.get_url(event, venue, area),
            json.dumps({"space_ids": [space3.pk, space1.pk, space2.pk]}),
            content_type="application/json",
        )

        assert response.status_code == HTTPStatus.OK
        assert response.json() == {"success": True}

        space1.refresh_from_db()
        space2.refresh_from_db()
        space3.refresh_from_db()
        assert space3.order == 0  # First in new order
        assert space1.order == 1  # Second in new order
        assert space2.order == 1 + 1  # Third in new order

    def test_post_returns_error_for_invalid_json(
        self, authenticated_client, active_user, sphere, event
    ):
        """Invalid JSON returns 400 error."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")
        area = Area.objects.create(venue=venue, name="East Wing", slug="east-wing")

        response = authenticated_client.post(
            self.get_url(event, venue, area),
            "not json",
            content_type="application/json",
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json() == {"error": "Invalid JSON"}

    def test_post_returns_error_for_missing_space_ids(
        self, authenticated_client, active_user, sphere, event
    ):
        """Missing space_ids returns 400 error."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")
        area = Area.objects.create(venue=venue, name="East Wing", slug="east-wing")

        response = authenticated_client.post(
            self.get_url(event, venue, area),
            json.dumps({}),
            content_type="application/json",
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json() == {"error": "Missing space_ids"}

    def test_post_ignores_spaces_from_other_areas(
        self, authenticated_client, active_user, sphere, event
    ):
        """Spaces from other areas are ignored."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")
        area1 = Area.objects.create(venue=venue, name="Area 1", slug="area-1")
        area2 = Area.objects.create(venue=venue, name="Area 2", slug="area-2")
        space1 = Space.objects.create(
            area=area1, name="Space 1", slug="space-1", order=0, event=area1.venue.event
        )
        space2 = Space.objects.create(
            area=area2, name="Space 2", slug="space-2", order=0, event=area2.venue.event
        )

        # Try to reorder with space from different area
        response = authenticated_client.post(
            self.get_url(event, venue, area1),
            json.dumps({"space_ids": [space2.pk, space1.pk]}),
            content_type="application/json",
        )

        assert response.status_code == HTTPStatus.OK
        # space2 is ignored, only space1 is reordered
        space1.refresh_from_db()
        space2.refresh_from_db()
        assert space1.order == 0  # Only valid space, first position
        assert space2.order == 0  # Unchanged

    def test_post_returns_error_for_invalid_venue_slug(
        self, authenticated_client, active_user, sphere, event
    ):
        """Invalid venue slug returns 404 error."""
        sphere.managers.add(active_user)
        url = reverse(
            "panel:space-reorder",
            kwargs={
                "slug": event.slug,
                "venue_slug": "nonexistent",
                "area_slug": "test-area",
            },
        )

        response = authenticated_client.post(
            url, json.dumps({"space_ids": []}), content_type="application/json"
        )

        assert response.status_code == HTTPStatus.NOT_FOUND
        assert response.json() == {"error": "Venue not found"}

    def test_post_returns_error_for_invalid_area_slug(
        self, authenticated_client, active_user, sphere, event
    ):
        """Invalid area slug returns 404 error."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")
        url = reverse(
            "panel:space-reorder",
            kwargs={
                "slug": event.slug,
                "venue_slug": venue.slug,
                "area_slug": "nonexistent",
            },
        )

        response = authenticated_client.post(
            url, json.dumps({"space_ids": []}), content_type="application/json"
        )

        assert response.status_code == HTTPStatus.NOT_FOUND
        assert response.json() == {"error": "Area not found"}

    def test_get_method_not_allowed(
        self, authenticated_client, active_user, sphere, event
    ):
        """GET request returns 405 Method Not Allowed."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")
        area = Area.objects.create(venue=venue, name="East Wing", slug="east-wing")

        response = authenticated_client.get(self.get_url(event, venue, area))

        assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED

    def test_post_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere
    ):
        """Invalid event slug triggers redirect on POST."""
        sphere.managers.add(active_user)
        url = reverse(
            "panel:space-reorder",
            kwargs={
                "slug": "nonexistent",
                "venue_slug": "test-venue",
                "area_slug": "test-area",
            },
        )

        response = authenticated_client.post(
            url, json.dumps({"space_ids": []}), content_type="application/json"
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )
