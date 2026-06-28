"""Tests for space edit page."""

from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import Area, Space, Venue
from ludamus.pacts import AreaDTO, EventDTO, SpaceDTO, VenueDTO
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


@pytest.mark.django_db
class TestSpaceEditPageView:
    """Tests for space edit page."""

    @staticmethod
    def get_url(event, venue, area, space):
        return reverse(
            "panel:space-edit",
            kwargs={
                "slug": event.slug,
                "venue_slug": venue.slug,
                "area_slug": area.slug,
                "space_slug": space.slug,
            },
        )

    def test_get_redirects_anonymous_user_to_login(self, client, event):
        """Anonymous users get redirect to login."""
        venue = Venue.objects.create(event=event, name="Test Venue", slug="test-venue")
        area = Area.objects.create(venue=venue, name="Test Area", slug="test-area")
        space = Space.objects.create(
            area=area, name="Test Space", slug="test-space", event=area.venue.event
        )
        url = self.get_url(event, venue, area, space)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_get_redirects_non_manager_user(self, authenticated_client, event):
        """Non-managers get error message and redirect home."""
        venue = Venue.objects.create(event=event, name="Test Venue", slug="test-venue")
        area = Area.objects.create(venue=venue, name="Test Area", slug="test-area")
        space = Space.objects.create(
            area=area, name="Test Space", slug="test-space", event=area.venue.event
        )

        response = authenticated_client.get(self.get_url(event, venue, area, space))

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
            "panel:space-edit",
            kwargs={
                "slug": "nonexistent",
                "venue_slug": "test-venue",
                "area_slug": "test-area",
                "space_slug": "test-space",
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
            "panel:space-edit",
            kwargs={
                "slug": event.slug,
                "venue_slug": "nonexistent",
                "area_slug": "test-area",
                "space_slug": "test-space",
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
            "panel:space-edit",
            kwargs={
                "slug": event.slug,
                "venue_slug": venue.slug,
                "area_slug": "nonexistent",
                "space_slug": "test-space",
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

    def test_get_redirects_on_invalid_space_slug(
        self, authenticated_client, active_user, sphere, event
    ):
        """Invalid space slug triggers error message and redirect."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Test Venue", slug="test-venue")
        area = Area.objects.create(venue=venue, name="Test Area", slug="test-area")
        url = reverse(
            "panel:space-edit",
            kwargs={
                "slug": event.slug,
                "venue_slug": venue.slug,
                "area_slug": area.slug,
                "space_slug": "nonexistent",
            },
        )

        response = authenticated_client.get(url)

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

    def test_get_ok_for_sphere_manager(
        self, authenticated_client, active_user, sphere, event
    ):
        """Manager can view form with correct context."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")
        area = Area.objects.create(venue=venue, name="East Wing", slug="east-wing")
        space = Space.objects.create(
            area=area,
            name="Room 101",
            slug="room-101",
            capacity=50,
            event=area.venue.event,
        )

        response = authenticated_client.get(self.get_url(event, venue, area, space))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/space-edit.html",
            context_data={
                "active_nav": "venues",
                "area": AreaDTO.model_validate(area),
                "current_event": EventDTO.model_validate(event),
                "events": [EventDTO.model_validate(event)],
                "form": ANY,
                "is_proposal_active": False,
                "space": SpaceDTO.model_validate(space),
                "stats": {
                    "hosts_count": 0,
                    "pending_proposals": 0,
                    "rooms_count": 1,  # The space we created
                    "scheduled_sessions": 0,
                    "total_proposals": 0,
                    "total_sessions": 0,
                },
                "venue": VenueDTO.model_validate(venue),
            },
        )

    def test_get_form_prefilled_with_space_data(
        self, authenticated_client, active_user, sphere, event
    ):
        """Form is prefilled with existing space data."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")
        area = Area.objects.create(venue=venue, name="East Wing", slug="east-wing")
        space = Space.objects.create(
            area=area,
            name="Room 101",
            slug="room-101",
            capacity=50,
            event=area.venue.event,
        )

        response = authenticated_client.get(self.get_url(event, venue, area, space))

        form = response.context["form"]
        assert form.initial["name"] == "Room 101"
        assert form.initial["capacity"] == 40 + 10  # capacity

    def test_post_redirects_anonymous_user_to_login(self, client, event):
        """Anonymous users get redirect to login."""
        venue = Venue.objects.create(event=event, name="Test Venue", slug="test-venue")
        area = Area.objects.create(venue=venue, name="Test Area", slug="test-area")
        space = Space.objects.create(
            area=area, name="Test Space", slug="test-space", event=area.venue.event
        )
        url = self.get_url(event, venue, area, space)

        response = client.post(url, {"name": "Updated Space"})

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_post_redirects_non_manager_user(self, authenticated_client, event):
        """Non-managers get error message and redirect home."""
        venue = Venue.objects.create(event=event, name="Test Venue", slug="test-venue")
        area = Area.objects.create(venue=venue, name="Test Area", slug="test-area")
        space = Space.objects.create(
            area=area, name="Test Space", slug="test-space", event=area.venue.event
        )

        response = authenticated_client.post(
            self.get_url(event, venue, area, space), {"name": "Updated Space"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_post_updates_space_for_sphere_manager(
        self, authenticated_client, active_user, sphere, event
    ):
        """Valid POST updates space and redirects to area detail."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")
        area = Area.objects.create(venue=venue, name="East Wing", slug="east-wing")
        space = Space.objects.create(
            area=area, name="Room 101", slug="room-101", event=area.venue.event
        )

        response = authenticated_client.post(
            self.get_url(event, venue, area, space), {"name": "Room 102"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Space updated successfully.")],
            url=reverse(
                "panel:area-detail",
                kwargs={
                    "slug": event.slug,
                    "venue_slug": venue.slug,
                    "area_slug": area.slug,
                },
            ),
        )
        space.refresh_from_db()
        assert space.name == "Room 102"
        assert space.slug == "room-102"

    def test_post_updates_space_capacity(
        self, authenticated_client, active_user, sphere, event
    ):
        """POST updates space capacity."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")
        area = Area.objects.create(venue=venue, name="East Wing", slug="east-wing")
        space = Space.objects.create(
            area=area,
            name="Room 101",
            slug="room-101",
            capacity=None,
            event=area.venue.event,
        )

        authenticated_client.post(
            self.get_url(event, venue, area, space),
            {"name": "Room 101", "capacity": "100"},
        )

        space.refresh_from_db()
        assert space.capacity == 90 + 10  # capacity

    def test_post_generates_unique_slug_on_name_change(
        self, authenticated_client, active_user, sphere, event
    ):
        """Changing name to existing slug generates unique slug."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")
        area = Area.objects.create(venue=venue, name="East Wing", slug="east-wing")
        Space.objects.create(
            area=area, name="Room 101", slug="room-101", event=area.venue.event
        )
        space2 = Space.objects.create(
            area=area, name="Room 102", slug="room-102", event=area.venue.event
        )

        authenticated_client.post(
            self.get_url(event, venue, area, space2), {"name": "Room 101"}
        )

        space2.refresh_from_db()
        assert space2.name == "Room 101"
        assert space2.slug.startswith("room-101-")

    def test_post_shows_error_for_empty_name(
        self, authenticated_client, active_user, sphere, event
    ):
        """Missing name shows form error."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")
        area = Area.objects.create(venue=venue, name="East Wing", slug="east-wing")
        space = Space.objects.create(
            area=area, name="Room 101", slug="room-101", event=area.venue.event
        )

        response = authenticated_client.post(
            self.get_url(event, venue, area, space), {"name": ""}
        )

        assert response.status_code == HTTPStatus.OK
        assert "panel/space-edit.html" in str(response.template_name)
        assert "Space name is required" in str(response.context["form"].errors)
        space.refresh_from_db()
        assert space.name == "Room 101"  # Not updated

    def test_post_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere
    ):
        """Invalid event slug triggers error message and redirect on POST."""
        sphere.managers.add(active_user)
        url = reverse(
            "panel:space-edit",
            kwargs={
                "slug": "nonexistent",
                "venue_slug": "test-venue",
                "area_slug": "test-area",
                "space_slug": "test-space",
            },
        )

        response = authenticated_client.post(url, {"name": "Updated Space"})

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
            "panel:space-edit",
            kwargs={
                "slug": event.slug,
                "venue_slug": "nonexistent",
                "area_slug": "test-area",
                "space_slug": "test-space",
            },
        )

        response = authenticated_client.post(url, {"name": "Updated Space"})

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
            "panel:space-edit",
            kwargs={
                "slug": event.slug,
                "venue_slug": venue.slug,
                "area_slug": "nonexistent",
                "space_slug": "test-space",
            },
        )

        response = authenticated_client.post(url, {"name": "Updated Space"})

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
        """Invalid space slug triggers error message and redirect on POST."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Test Venue", slug="test-venue")
        area = Area.objects.create(venue=venue, name="Test Area", slug="test-area")
        url = reverse(
            "panel:space-edit",
            kwargs={
                "slug": event.slug,
                "venue_slug": venue.slug,
                "area_slug": area.slug,
                "space_slug": "nonexistent",
            },
        )

        response = authenticated_client.post(url, {"name": "Updated Space"})

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
