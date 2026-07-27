from http import HTTPStatus

import pytest
from django.contrib import messages
from django.urls import reverse

from tests.integration.conftest import EventFactory
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


class TestPanelIndexRedirectView:
    """Tests for /panel/ redirect view."""

    URL = reverse("panel:index")

    def test_redirects_anonymous_user_to_login(self, client):
        response = client.get(self.URL)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={self.URL}"
        )

    def test_redirects_non_manager_user(self, authenticated_client):
        response = authenticated_client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_redirects_to_first_event(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.URL)

        assert_response(response, HTTPStatus.FOUND, url=f"/panel/event/{event.slug}/")

    def test_redirects_to_home_when_no_events(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.INFO, "No events available for this sphere.")],
            url="/",
        )


class TestEventIndexPageView:
    """Tests for /panel/event/<slug>/ view."""

    @staticmethod
    def get_url(event):
        return reverse("panel:event-index", kwargs={"slug": event.slug})

    def test_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    @pytest.mark.usefixtures("panel_access_user")
    def test_ok_for_manager_and_superuser(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event))

        current_event = response.context["current_event"]
        events = response.context["events"]
        is_proposal_active = response.context["is_proposal_active"]
        assert current_event.pk == event.pk
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/index.html",
            context_data={
                "current_event": current_event,
                "events": events,
                "is_proposal_active": is_proposal_active,
                "stats": {
                    "hosts_count": 0,
                    "pending_proposals": 0,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 0,
                    "total_sessions": 0,
                },
                "active_nav": "index",
            },
        )

    def test_shows_events_for_sphere(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event))

        current_event = response.context["current_event"]
        events = response.context["events"]
        is_proposal_active = response.context["is_proposal_active"]
        assert len(events) == 1
        assert events[0].pk == event.pk
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/index.html",
            context_data={
                "current_event": current_event,
                "events": events,
                "is_proposal_active": is_proposal_active,
                "stats": {
                    "hosts_count": 0,
                    "pending_proposals": 0,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 0,
                    "total_sessions": 0,
                },
                "active_nav": "index",
            },
        )

    def test_shows_stats_for_current_event(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event))

        current_event = response.context["current_event"]
        events = response.context["events"]
        is_proposal_active = response.context["is_proposal_active"]
        stats = response.context["stats"]
        assert "total_sessions" in stats
        assert "pending_proposals" in stats
        assert "scheduled_sessions" in stats
        assert "hosts_count" in stats
        assert "rooms_count" in stats
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/index.html",
            context_data={
                "current_event": current_event,
                "events": events,
                "is_proposal_active": is_proposal_active,
                "stats": stats,
                "active_nav": "index",
            },
        )

    def test_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse("panel:event-index", kwargs={"slug": "nonexistent"})

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_can_view_different_events(
        self, authenticated_client, active_user, sphere, event, faker
    ):
        sphere.managers.add(active_user)
        event2 = EventFactory(sphere=sphere, slug=faker.slug())

        response = authenticated_client.get(self.get_url(event2))

        current_event = response.context["current_event"]
        events = response.context["events"]
        is_proposal_active = response.context["is_proposal_active"]
        assert current_event.pk == event2.pk
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/index.html",
            context_data={
                "current_event": current_event,
                "events": events,
                "is_proposal_active": is_proposal_active,
                "stats": {
                    "hosts_count": 0,
                    "pending_proposals": 0,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 0,
                    "total_sessions": 0,
                },
                "active_nav": "index",
            },
        )
