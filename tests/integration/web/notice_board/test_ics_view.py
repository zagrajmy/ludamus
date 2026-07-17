from http import HTTPStatus

from django.urls import reverse

from tests.integration.utils import assert_response, assert_response_404


class TestEncounterIcsView:
    def test_ok(self, client, encounter):
        url = reverse(
            "web:notice-board:encounter-ics",
            kwargs={"share_code": encounter.share_code},
        )

        response = client.get(url)

        assert_response(
            response, HTTPStatus.OK, cache_control={"public", "max-age=300"}
        )
        assert "text/calendar" in response["Content-Type"]
        content = response.content.decode()
        assert "BEGIN:VCALENDAR" in content
        assert encounter.title in content
        assert encounter.share_code in content

    def test_not_found(self, client):
        url = reverse("web:notice-board:encounter-ics", kwargs={"share_code": "XXXXXX"})

        response = client.get(url)

        assert_response_404(response)
