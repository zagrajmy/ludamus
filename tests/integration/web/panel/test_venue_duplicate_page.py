"""Integration tests for /panel/event/<slug>/venues/<venue_slug>/do/duplicate page."""

from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import Area, Space, Venue
from ludamus.pacts import EventDTO, VenueDTO
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


class TestVenueDuplicatePageView:
    """Tests for /panel/event/<slug>/venues/<venue_slug>/do/duplicate page."""

    @staticmethod
    def get_url(event, venue):
        return reverse(
            "panel:venue-duplicate",
            kwargs={"slug": event.slug, "venue_slug": venue.slug},
        )

    def test_get_redirects_anonymous_user_to_login(self, client, event):
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")
        url = self.get_url(event, venue)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_get_redirects_non_manager_user(self, authenticated_client, event):
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")

        response = authenticated_client.get(self.get_url(event, venue))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_get_shows_duplicate_form_for_manager(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")

        response = authenticated_client.get(self.get_url(event, venue))

        event_dto = EventDTO.model_validate(event)
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "active_nav": "venues",
                "current_event": event_dto,
                "events": [event_dto],
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
            template_name="panel/venue-duplicate.html",
        )

    def test_get_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")
        url = reverse(
            "panel:venue-duplicate",
            kwargs={"slug": "nonexistent", "venue_slug": venue.slug},
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
        sphere.managers.add(active_user)
        url = reverse(
            "panel:venue-duplicate",
            kwargs={"slug": event.slug, "venue_slug": "nonexistent"},
        )

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Venue not found.")],
            url=f"/panel/event/{event.slug}/venues/",
        )

    def test_post_duplicates_venue_with_areas_and_spaces(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        venue = Venue.objects.create(
            event=event, name="Main Hall", slug="main-hall", address="123 Main St"
        )
        area = Area.objects.create(
            venue=venue, name="Ground Floor", slug="ground-floor"
        )
        Space.objects.create(
            area=area,
            name="Room 101",
            slug="room-101",
            capacity=50,
            event=area.venue.event,
        )
        Space.objects.create(
            area=area,
            name="Room 102",
            slug="room-102",
            capacity=30,
            event=area.venue.event,
        )

        response = authenticated_client.post(
            self.get_url(event, venue), {"name": "Main Hall Copy"}
        )

        # Check redirect
        new_venue = Venue.objects.get(name="Main Hall Copy")
        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Venue duplicated successfully.")],
            url=f"/panel/event/{event.slug}/venues/{new_venue.slug}/",
        )

        # Verify venue was duplicated
        assert new_venue.address == "123 Main St"

        # Verify areas were copied
        new_area = Area.objects.get(venue=new_venue)
        assert new_area.name == "Ground Floor"

        # Verify spaces were copied - 1 + 1 (original 2 spaces)
        new_spaces = Space.objects.filter(area=new_area)
        assert new_spaces.count() == 1 + 1  # 2 spaces copied
        assert new_spaces.filter(name="Room 101", capacity=50).exists()
        assert new_spaces.filter(name="Room 102", capacity=30).exists()

    def test_post_returns_form_on_validation_error(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")

        response = authenticated_client.post(self.get_url(event, venue), {"name": ""})

        event_dto = EventDTO.model_validate(event)
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "active_nav": "venues",
                "current_event": event_dto,
                "events": [event_dto],
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
            template_name="panel/venue-duplicate.html",
        )
        # Verify no new venue was created
        assert Venue.objects.filter(event=event).count() == 1

    def test_post_redirects_on_invalid_venue_slug(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        url = reverse(
            "panel:venue-duplicate",
            kwargs={"slug": event.slug, "venue_slug": "nonexistent"},
        )

        response = authenticated_client.post(url, {"name": "New Venue"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Venue not found.")],
            url=f"/panel/event/{event.slug}/venues/",
        )

    def test_post_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")
        url = reverse(
            "panel:venue-duplicate",
            kwargs={"slug": "nonexistent", "venue_slug": venue.slug},
        )

        response = authenticated_client.post(url, {"name": "New Venue"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )
