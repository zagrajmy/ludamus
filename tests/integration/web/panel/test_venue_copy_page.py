"""Integration tests for /panel/event/<slug>/venues/<venue_slug>/do/copy page."""

from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import Area, Space, Venue
from ludamus.pacts import EventDTO, VenueDTO
from tests.integration.conftest import EventFactory
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


class TestVenueCopyPageView:
    """Tests for /panel/event/<slug>/venues/<venue_slug>/do/copy page."""

    @staticmethod
    def get_url(event, venue):
        return reverse(
            "panel:venue-copy", kwargs={"slug": event.slug, "venue_slug": venue.slug}
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

    def test_get_shows_copy_form_for_manager(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")
        # Create another event for copy target
        second_event = EventFactory(
            name="Second Event", slug="second-event", sphere=sphere
        )

        response = authenticated_client.get(self.get_url(event, venue))

        event_dto = EventDTO.model_validate(event)
        second_event_dto = EventDTO.model_validate(second_event)
        events = sorted(
            [event_dto, second_event_dto], key=lambda e: e.start_time, reverse=True
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "active_nav": "venues",
                "current_event": event_dto,
                "events": events,
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
            template_name="panel/venue-copy.html",
        )

    def test_get_redirects_when_no_other_events_available(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")

        response = authenticated_client.get(self.get_url(event, venue))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.WARNING, "No other events available to copy to.")],
            url=f"/panel/event/{event.slug}/venues/{venue.slug}/",
        )

    def test_get_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")
        url = reverse(
            "panel:venue-copy", kwargs={"slug": "nonexistent", "venue_slug": venue.slug}
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
            "panel:venue-copy", kwargs={"slug": event.slug, "venue_slug": "nonexistent"}
        )

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Venue not found.")],
            url=f"/panel/event/{event.slug}/venues/",
        )

    def test_post_copies_venue_to_another_event(
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

        # Create target event
        target_event = EventFactory(
            name="Second Event", slug="second-event", sphere=sphere
        )

        response = authenticated_client.post(
            self.get_url(event, venue), {"target_event": str(target_event.pk)}
        )

        # Check redirect - stays on venues list after copying
        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Venue copied to Second Event successfully.")],
            url=f"/panel/event/{event.slug}/venues/",
        )

        # Verify venue was copied to target event
        new_venue = Venue.objects.get(event=target_event, name="Main Hall")
        assert new_venue.address == "123 Main St"

        # Verify areas were copied
        new_area = Area.objects.get(venue=new_venue)
        assert new_area.name == "Ground Floor"

        # Verify spaces were copied - 1 + 1 (original 2 spaces)
        new_spaces = Space.objects.filter(area=new_area)
        assert new_spaces.count() == 1 + 1  # 2 spaces copied
        assert new_spaces.filter(name="Room 101", capacity=50).exists()
        assert new_spaces.filter(name="Room 102", capacity=30).exists()

        # Verify original venue still exists
        assert Venue.objects.filter(pk=venue.pk).exists()

    def test_post_returns_form_on_validation_error(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        venue = Venue.objects.create(event=event, name="Main Hall", slug="main-hall")
        # Create another event for copy target
        second_event = EventFactory(
            name="Second Event", slug="second-event", sphere=sphere
        )

        response = authenticated_client.post(
            self.get_url(event, venue), {"target_event": ""}
        )

        event_dto = EventDTO.model_validate(event)
        second_event_dto = EventDTO.model_validate(second_event)
        events = sorted(
            [event_dto, second_event_dto], key=lambda e: e.start_time, reverse=True
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "active_nav": "venues",
                "current_event": event_dto,
                "events": events,
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
            template_name="panel/venue-copy.html",
        )

    def test_post_redirects_on_invalid_venue_slug(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        target_event = EventFactory(
            name="Second Event", slug="second-event", sphere=sphere
        )
        url = reverse(
            "panel:venue-copy", kwargs={"slug": event.slug, "venue_slug": "nonexistent"}
        )

        response = authenticated_client.post(
            url, {"target_event": str(target_event.pk)}
        )

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
        target_event = EventFactory(
            name="Second Event", slug="second-event", sphere=sphere
        )
        url = reverse(
            "panel:venue-copy", kwargs={"slug": "nonexistent", "venue_slug": venue.slug}
        )

        response = authenticated_client.post(
            url, {"target_event": str(target_event.pk)}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )
