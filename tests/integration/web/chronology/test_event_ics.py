from datetime import UTC, timedelta
from http import HTTPStatus

import pytest
from django.urls import reverse
from django.utils import timezone

from tests.integration.utils import assert_response, assert_response_404


@pytest.mark.django_db
class TestEventICSView:
    def _url(self, slug):
        return reverse("web:chronology:event-ics", kwargs={"slug": slug})

    def test_ok_serves_single_vevent_with_location(self, client, event):
        event.address = "Hala Stulecia\nWystawowa 1\nWrocław"
        event.save()

        response = client.get(self._url(event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            contains=[
                "BEGIN:VCALENDAR",
                "BEGIN:VEVENT",
                f"DTSTART:{event.start_time.astimezone(UTC):%Y%m%dT%H%M%SZ}",
                f"DTEND:{event.end_time.astimezone(UTC):%Y%m%dT%H%M%SZ}",
                f"SUMMARY:{event.name}",
                "LOCATION:Hala Stulecia\\, Wystawowa 1\\, Wrocław",
                f"URL:http://testserver/event/{event.slug}/",
                "END:VCALENDAR",
            ],
        )
        assert response["Content-Type"] == "text/calendar; charset=utf-8"
        assert (
            response["Content-Disposition"]
            == f'attachment; filename="{event.slug}.ics"'
        )
        assert response["Cache-Control"] == "private, max-age=180"
        assert "Cookie" in response["Vary"]

    def test_event_without_address_has_no_location_line(self, client, event):
        response = client.get(self._url(event.slug))

        assert_response(response, HTTPStatus.OK, not_contains="LOCATION:")

    def test_unpublished_event_is_not_found_for_anonymous(self, client, event):
        event.publication_time = timezone.now() + timedelta(days=1)
        event.save()

        response = client.get(self._url(event.slug))

        assert_response_404(response)

    def test_missing_event_is_not_found(self, client):
        response = client.get(self._url("does-not-exist"))

        assert_response_404(response)
