"""Tests for space create page."""

from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import Area, Space, Venue
from ludamus.pacts import AreaDTO, EventDTO, VenueDTO
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


@pytest.mark.django_db
class TestSpaceCreatePageView:
    """Tests for space create page."""

    @staticmethod
    def get_url(event, venue, area):
        return reverse(
            "panel:space-create",
            kwargs={
                "slug": event.slug,
                "venue_slug": venue.slug,
                "area_slug": area.slug,
            },
        )

    def test_get_redirects_anonymous_user_to_login(self, client, event):
        """Anonymous users get redirect to login."""
        venue = Venue.objects.create(event=event, name="Test Venue", slug="test-venue")
        area = Area.objects.create(venue=venue, name="Test Area", slug="test-area")
        url = self.get_url(event, venue, area)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_get_redirects_non_manager_user(self, authenticated_client, event):
        """Non-managers get error message and redirect home."""
        venue = Venue.objects.create(event=event, name="Test Venue", slug="test-venue")
        area = Area.objects.create(venue=venue, name="Test Area", slug="test-area")

        response = authenticated_client.get(self.get_url(event, venue, area))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_get_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere
    ):
        """Invalid event slug triggers error message and redirect."""
        sphere.managers.add(active_user)
        url = reverse(
            "panel:space-create",
            kwargs={
                "slug": "nonexistent",
                "venue_slug": "test-venue",
                "area_slug": "test-area",
            },
        )

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_get_redirects_on_invalid_venue_slug(
        self, authenticated_client, active_user, sphere, event
    ):
        """Invalid venue slug triggers error message and redirect."""
        sphere.managers.add(active_user)
        url = reverse(
            "panel:space-create",
            kwargs={
                "slug": event.slug,
                "venue_slug": "nonexistent",
                "area_slug": "test-area",
            },
        )

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Venue not found.")],
            url=reverse("panel:venues", kwargs={"slug": event.slug}),
        )

    def test_get_redirects_on_invalid_area_slug(
        self, authenticated_client, active_user, sphere, event
    ):
        """Invalid area slug triggers error message and redirect."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Test Venue", slug="test-venue")
        url = reverse(
            "panel:space-create",
            kwargs={
                "slug": event.slug,
                "venue_slug": venue.slug,
                "area_slug": "nonexistent",
            },
        )

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Area not found.")],
            url=reverse(
                "panel:venue-detail",
                kwargs={"slug": event.slug, "venue_slug": venue.slug},
            ),
        )

    def test_get_ok_for_sphere_manager(
        self, authenticated_client, active_user, sphere, event
    ):
        """Manager can view form with correct context."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")
        area = Area.objects.create(venue=venue, name="East Wing", slug="east-wing")

        response = authenticated_client.get(self.get_url(event, venue, area))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/space-create.html",
            context_data={
                "active_nav": "venues",
                "area": AreaDTO.model_validate(area),
                "current_event": EventDTO.model_validate(event),
                "events": [EventDTO.model_validate(event)],
                "form": ANY,
                "is_proposal_active": False,
                "stats": {
                    "hosts_count": 0,
                    "pending_proposals": 0,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 0,
                    "total_sessions": 0,
                },
                "venue": VenueDTO.model_validate(venue),
            },
        )

    def test_post_redirects_anonymous_user_to_login(self, client, event):
        """Anonymous users get redirect to login."""
        venue = Venue.objects.create(event=event, name="Test Venue", slug="test-venue")
        area = Area.objects.create(venue=venue, name="Test Area", slug="test-area")
        url = self.get_url(event, venue, area)

        response = client.post(url, {"name": "Test Space"})

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_post_redirects_non_manager_user(self, authenticated_client, event):
        """Non-managers get error message and redirect home."""
        venue = Venue.objects.create(event=event, name="Test Venue", slug="test-venue")
        area = Area.objects.create(venue=venue, name="Test Area", slug="test-area")

        response = authenticated_client.post(
            self.get_url(event, venue, area), {"name": "Test Space"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_post_creates_space_for_sphere_manager(
        self, authenticated_client, active_user, sphere, event
    ):
        """Valid POST creates space and redirects to area detail."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")
        area = Area.objects.create(venue=venue, name="East Wing", slug="east-wing")

        response = authenticated_client.post(
            self.get_url(event, venue, area), {"name": "Room 101"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Space created successfully.")],
            url=reverse(
                "panel:area-detail",
                kwargs={
                    "slug": event.slug,
                    "venue_slug": venue.slug,
                    "area_slug": area.slug,
                },
            ),
        )
        assert Space.objects.filter(area=area, name="Room 101").exists()

    def test_post_creates_space_with_capacity(
        self, authenticated_client, active_user, sphere, event
    ):
        """POST with capacity saves capacity."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")
        area = Area.objects.create(venue=venue, name="East Wing", slug="east-wing")

        authenticated_client.post(
            self.get_url(event, venue, area), {"name": "Room 101", "capacity": "50"}
        )

        space = Space.objects.get(area=area, name="Room 101")
        assert space.capacity == 40 + 10  # capacity

    def test_post_auto_generates_slug(
        self, authenticated_client, active_user, sphere, event
    ):
        """Slug is auto-generated from name."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")
        area = Area.objects.create(venue=venue, name="East Wing", slug="east-wing")

        authenticated_client.post(
            self.get_url(event, venue, area), {"name": "Room One Zero One"}
        )

        space = Space.objects.get(area=area, name="Room One Zero One")
        assert space.slug == "room-one-zero-one"

    def test_post_generates_unique_slug_on_conflict(
        self, authenticated_client, active_user, sphere, event
    ):
        """Duplicate names get numbered slugs."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")
        area = Area.objects.create(venue=venue, name="East Wing", slug="east-wing")
        Space.objects.create(
            area=area, name="Room 101", slug="room-101", event=area.venue.event
        )

        authenticated_client.post(
            self.get_url(event, venue, area), {"name": "Room 101"}
        )

        spaces = Space.objects.filter(area=area).order_by("pk")
        assert spaces[0].slug == "room-101"
        assert spaces[1].slug.startswith("room-101-")

    def test_post_shows_error_for_empty_name(
        self, authenticated_client, active_user, sphere, event
    ):
        """Missing name shows form error."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")
        area = Area.objects.create(venue=venue, name="East Wing", slug="east-wing")

        response = authenticated_client.post(
            self.get_url(event, venue, area), {"name": ""}
        )

        assert response.status_code == HTTPStatus.OK
        assert "panel/space-create.html" in str(response.template_name)
        assert "Space name is required" in str(response.context["form"].errors)
        assert not Space.objects.filter(area=area).exists()

    def test_post_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere
    ):
        """Invalid event slug triggers error message and redirect on POST."""
        sphere.managers.add(active_user)
        url = reverse(
            "panel:space-create",
            kwargs={
                "slug": "nonexistent",
                "venue_slug": "test-venue",
                "area_slug": "test-area",
            },
        )

        response = authenticated_client.post(url, {"name": "Test Space"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_post_redirects_on_invalid_venue_slug(
        self, authenticated_client, active_user, sphere, event
    ):
        """Invalid venue slug triggers error message and redirect on POST."""
        sphere.managers.add(active_user)
        url = reverse(
            "panel:space-create",
            kwargs={
                "slug": event.slug,
                "venue_slug": "nonexistent",
                "area_slug": "test-area",
            },
        )

        response = authenticated_client.post(url, {"name": "Test Space"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Venue not found.")],
            url=reverse("panel:venues", kwargs={"slug": event.slug}),
        )

    def test_post_redirects_on_invalid_area_slug(
        self, authenticated_client, active_user, sphere, event
    ):
        """Invalid area slug triggers error message and redirect on POST."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Test Venue", slug="test-venue")
        url = reverse(
            "panel:space-create",
            kwargs={
                "slug": event.slug,
                "venue_slug": venue.slug,
                "area_slug": "nonexistent",
            },
        )

        response = authenticated_client.post(url, {"name": "Test Space"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Area not found.")],
            url=reverse(
                "panel:venue-detail",
                kwargs={"slug": event.slug, "venue_slug": venue.slug},
            ),
        )
