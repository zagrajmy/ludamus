"""Tests for area detail page."""

from http import HTTPStatus

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import Area, Space, Venue
from ludamus.pacts import AreaDTO, EventDTO, VenueDTO
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


@pytest.mark.django_db
class TestAreaDetailPageView:
    """Tests for /panel/event/<slug>/venues/<venue_slug>/areas/<area_slug>/."""

    @staticmethod
    def get_url(event, venue, area):
        return reverse(
            "panel:area-detail",
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
            "panel:area-detail",
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
            "panel:area-detail",
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
            "panel:area-detail",
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
        """Manager can view area details with correct context."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")
        area = Area.objects.create(venue=venue, name="East Wing", slug="east-wing")

        response = authenticated_client.get(self.get_url(event, venue, area))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/area-detail.html",
            context_data={
                "active_nav": "venues",
                "area": AreaDTO.model_validate(area),
                "current_event": EventDTO.model_validate(event),
                "events": [EventDTO.model_validate(event)],
                "is_proposal_active": False,
                "spaces": [],
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

    def test_get_shows_spaces_list(
        self, authenticated_client, active_user, sphere, event
    ):
        """Manager sees list of spaces in area."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")
        area = Area.objects.create(venue=venue, name="East Wing", slug="east-wing")
        Space.objects.create(
            area=area,
            name="Room 101",
            slug="room-101",
            capacity=50,
            event=area.venue.event,
        )

        response = authenticated_client.get(self.get_url(event, venue, area))

        assert response.status_code == HTTPStatus.OK
        spaces = response.context["spaces"]
        assert len(spaces) == 1
        assert spaces[0].name == "Room 101"
        assert spaces[0].capacity == 40 + 10  # capacity
