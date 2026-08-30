"""Disabling the Events page hides the whole group, not just /events.

The event detail page and its sub-pages are the Events group; leaving them
served while /events 404s would contradict what the setting promises.
"""

from http import HTTPStatus

import pytest
from django.urls import reverse

from tests.integration.utils import assert_response, assert_response_404
from tests.integration.web.chronology.helpers import event_page_context


@pytest.fixture
def events_disabled(sphere):
    sphere.enabled_pages = ["encounters"]
    sphere.default_page = "encounters"
    sphere.save()


@pytest.fixture
def timeline_only(sphere):
    sphere.enabled_pages = ["timeline"]
    sphere.default_page = "timeline"
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


@pytest.mark.usefixtures("timeline_only")
class TestEventContentWithTimelineOnly:
    """The timeline links into event content, so it stays served.

    Only the /events landing itself is the disabled page.
    """

    def test_event_detail_ok(self, client, event):
        url = reverse("web:chronology:event", kwargs={"slug": event.slug})

        response = client.get(url)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(event, url=url),
            template_name=["chronology/event.html"],
        )

    def test_events_index_404(self, client):
        response = client.get(reverse("web:events"))

        assert_response_404(response)
