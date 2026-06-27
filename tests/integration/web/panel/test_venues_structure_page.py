"""Integration tests for /panel/event/<slug>/venues/structure/ page."""

from http import HTTPStatus

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import Area, Space, Venue
from ludamus.pacts import EventDTO, SpaceDTO, VenueDTO
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


@pytest.mark.django_db
class TestVenuesStructurePageView:
    """Tests for /panel/event/<slug>/venues/structure/ page."""

    @staticmethod
    def get_url(event):
        return reverse("panel:venues-structure", kwargs={"slug": event.slug})

    def test_redirects_anonymous_user_to_login(self, client, event):
        """Anonymous users get redirect to login."""
        url = self.get_url(event)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_redirects_non_manager_user(self, authenticated_client, event):
        """Non-managers get error message and redirect home."""
        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere
    ):
        """Invalid event slug triggers error message and redirect."""
        sphere.managers.add(active_user)
        url = reverse("panel:venues-structure", kwargs={"slug": "nonexistent"})

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_ok_for_sphere_manager_empty_state(
        self, authenticated_client, active_user, sphere, event
    ):
        """Manager can view page with empty structure."""
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/venues-structure.html",
            context_data={
                "current_event": EventDTO.model_validate(event),
                "events": [EventDTO.model_validate(event)],
                "is_proposal_active": False,
                "stats": {
                    "hosts_count": 0,
                    "pending_proposals": 0,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 0,
                    "total_sessions": 0,
                },
                "active_nav": "venues",
                "venue_structure": [],
                "total_venues": 0,
                "total_areas": 0,
                "total_spaces": 0,
            },
        )

    def test_returns_structure_with_single_venue_no_areas(
        self, authenticated_client, active_user, sphere, event
    ):
        """Structure includes venue with no areas."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(
            event=event, name="Conference Center", slug="conference-center", order=0
        )

        response = authenticated_client.get(self.get_url(event))

        assert response.context["venue_structure"] == [
            {"venue": VenueDTO.model_validate(venue), "areas": []}
        ]
        assert response.context["total_venues"] == 1
        assert response.context["total_areas"] == 0
        assert response.context["total_spaces"] == 0

    def test_returns_structure_with_areas_no_spaces(
        self, authenticated_client, active_user, sphere, event
    ):
        """Structure includes areas without spaces."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(
            event=event, name="Main Hall", slug="main-hall", order=0
        )
        area = Area.objects.create(
            venue=venue,
            name="Ground Floor",
            slug="ground-floor",
            description="Main entrance level",
            order=0,
        )

        response = authenticated_client.get(self.get_url(event))

        structure = response.context["venue_structure"]
        assert len(structure) == 1
        assert structure[0]["venue"].pk == venue.pk
        assert structure[0]["venue"].name == "Main Hall"
        assert structure[0]["venue"].areas_count == 1
        assert len(structure[0]["areas"]) == 1
        assert structure[0]["areas"][0]["area"].pk == area.pk
        assert structure[0]["areas"][0]["area"].name == "Ground Floor"
        assert structure[0]["areas"][0]["area"].spaces_count == 0
        assert structure[0]["areas"][0]["spaces"] == []
        assert response.context["total_venues"] == 1
        assert response.context["total_areas"] == 1
        assert response.context["total_spaces"] == 0

    def test_returns_full_hierarchical_structure(
        self, authenticated_client, active_user, sphere, event
    ):
        """Structure includes venues, areas, and spaces in hierarchy."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(
            event=event,
            name="Convention Center",
            slug="convention-center",
            address="123 Main St",
            order=0,
        )
        area = Area.objects.create(
            venue=venue,
            name="East Wing",
            slug="east-wing",
            description="Conference rooms",
            order=0,
        )
        space = Space.objects.create(
            area=area,
            name="Room 101",
            slug="room-101",
            capacity=50,
            order=0,
            event=area.venue.event,
        )

        response = authenticated_client.get(self.get_url(event))

        structure = response.context["venue_structure"]
        assert len(structure) == 1
        assert structure[0]["venue"].pk == venue.pk
        assert len(structure[0]["areas"]) == 1
        assert structure[0]["areas"][0]["area"].pk == area.pk
        assert len(structure[0]["areas"][0]["spaces"]) == 1
        assert structure[0]["areas"][0]["spaces"][0] == SpaceDTO.model_validate(space)
        assert response.context["total_venues"] == 1
        assert response.context["total_areas"] == 1
        assert response.context["total_spaces"] == 1

    def test_returns_multiple_venues_with_nested_structure(
        self, authenticated_client, active_user, sphere, event
    ):
        """Multiple venues are returned with their nested areas and spaces."""
        sphere.managers.add(active_user)
        # First venue with 2 areas, each with spaces
        venue1 = Venue.objects.create(
            event=event, name="Building A", slug="building-a", order=0
        )
        area1 = Area.objects.create(
            venue=venue1, name="Floor 1", slug="floor-1", order=0
        )
        Space.objects.create(
            area=area1, name="Room 1A", slug="room-1a", order=0, event=area1.venue.event
        )
        Space.objects.create(
            area=area1, name="Room 1B", slug="room-1b", order=1, event=area1.venue.event
        )
        area2 = Area.objects.create(
            venue=venue1, name="Floor 2", slug="floor-2", order=1
        )
        Space.objects.create(
            area=area2, name="Room 2A", slug="room-2a", order=0, event=area2.venue.event
        )

        # Second venue with 1 area
        venue2 = Venue.objects.create(
            event=event, name="Building B", slug="building-b", order=1
        )
        area3 = Area.objects.create(
            venue=venue2, name="Main Hall", slug="main-hall", order=0
        )
        Space.objects.create(
            area=area3, name="Stage", slug="stage", order=0, event=area3.venue.event
        )

        response = authenticated_client.get(self.get_url(event))

        structure = response.context["venue_structure"]
        assert len(structure) == 1 + 1  # 2 venues
        # First venue
        assert structure[0]["venue"].name == "Building A"
        assert len(structure[0]["areas"]) == 1 + 1  # 2 areas
        assert len(structure[0]["areas"][0]["spaces"]) == 1 + 1  # 2 spaces in floor 1
        assert len(structure[0]["areas"][1]["spaces"]) == 1  # 1 space in floor 2
        # Second venue
        assert structure[1]["venue"].name == "Building B"
        assert len(structure[1]["areas"]) == 1  # 1 area
        assert len(structure[1]["areas"][0]["spaces"]) == 1  # 1 space

        assert response.context["total_venues"] == 1 + 1  # 2 venues
        assert response.context["total_areas"] == 1 + 1 + 1  # 3 areas total
        assert response.context["total_spaces"] == 1 + 1 + 1 + 1  # 4 spaces total

    def test_venues_ordered_by_order_field(
        self, authenticated_client, active_user, sphere, event
    ):
        """Venues are returned sorted by order field."""
        sphere.managers.add(active_user)
        venue_b = Venue.objects.create(
            event=event, name="Zeta Hall", slug="zeta-hall", order=2
        )
        venue_a = Venue.objects.create(
            event=event, name="Alpha Hall", slug="alpha-hall", order=1
        )

        response = authenticated_client.get(self.get_url(event))

        structure = response.context["venue_structure"]
        assert len(structure) == 1 + 1  # 2 venues
        assert structure[0]["venue"].pk == venue_a.pk  # order=1 first
        assert structure[1]["venue"].pk == venue_b.pk  # order=2 second

    def test_areas_ordered_by_order_field(
        self, authenticated_client, active_user, sphere, event
    ):
        """Areas within a venue are sorted by order field."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main", slug="main", order=0)
        area_z = Area.objects.create(venue=venue, name="Zone Z", slug="zone-z", order=2)
        area_a = Area.objects.create(venue=venue, name="Zone A", slug="zone-a", order=1)

        response = authenticated_client.get(self.get_url(event))

        areas = response.context["venue_structure"][0]["areas"]
        assert len(areas) == 1 + 1  # 2 areas
        assert areas[0]["area"].pk == area_a.pk  # order=1 first
        assert areas[1]["area"].pk == area_z.pk  # order=2 second

    def test_spaces_ordered_by_order_field(
        self, authenticated_client, active_user, sphere, event
    ):
        """Spaces within an area are sorted by order field."""
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Venue", slug="venue", order=0)
        area = Area.objects.create(venue=venue, name="Area", slug="area", order=0)
        space_z = Space.objects.create(
            area=area, name="Room Z", slug="room-z", order=2, event=area.venue.event
        )
        space_a = Space.objects.create(
            area=area, name="Room A", slug="room-a", order=1, event=area.venue.event
        )

        response = authenticated_client.get(self.get_url(event))

        spaces = response.context["venue_structure"][0]["areas"][0]["spaces"]
        assert len(spaces) == 1 + 1  # 2 spaces
        assert spaces[0].pk == space_a.pk  # order=1 first
        assert spaces[1].pk == space_z.pk  # order=2 second
