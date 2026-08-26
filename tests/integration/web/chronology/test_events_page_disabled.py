"""Disabling the Events page hides the whole group, not just /events.

The event detail page and its sub-pages are the Events group; leaving them
served while /events 404s would contradict what the setting promises.
"""

import pytest
from django.urls import reverse

from tests.integration.utils import assert_response_404


@pytest.fixture
def events_disabled(sphere):
    sphere.enabled_pages = ["encounters"]
    sphere.default_page = "encounters"
    sphere.save()


@pytest.mark.usefixtures("events_disabled")
class TestEventPagesWithGroupDisabled:
    def test_event_detail_404(self, client, event):
        response = client.get(
            reverse("web:chronology:event", kwargs={"slug": event.slug})
        )

        assert_response_404(response)

    def test_event_print_404(self, client, event):
        response = client.get(
            reverse("web:chronology:event-print", kwargs={"slug": event.slug})
        )

        assert_response_404(response)

    def test_session_enrollment_404(self, authenticated_client, event, session):
        response = authenticated_client.get(
            reverse(
                "web:chronology:session-enrollment",
                kwargs={"event_slug": event.slug, "session_id": session.pk},
            )
        )

        assert_response_404(response)

    def test_session_modal_404(self, client, event, session):
        response = client.get(
            reverse(
                "web:chronology:session-modal",
                kwargs={"event_slug": event.slug, "session_id": session.pk},
            )
        )

        assert_response_404(response)

    def test_session_propose_404(self, authenticated_client, event):
        response = authenticated_client.get(
            reverse("web:event:session-propose", kwargs={"event_slug": event.slug})
        )

        assert_response_404(response)

    def test_session_bookmark_404(self, authenticated_client, session):
        response = authenticated_client.post(
            reverse(
                "web:chronology:session-bookmark", kwargs={"session_id": session.pk}
            )
        )

        assert_response_404(response)
