from http import HTTPStatus

from django.urls import reverse

from tests.integration.utils import assert_response, assert_response_404


class TestEncounterQrView:
    def test_ok(self, client, encounter):
        url = reverse(
            "web:notice-board:encounter-qr", kwargs={"share_code": encounter.share_code}
        )

        response = client.get(url)

        assert_response(response, HTTPStatus.OK)
        directives = response["Cache-Control"].split(", ")
        assert "public" in directives
        assert "max-age=86400" in directives
        assert response["Content-Type"] == "image/svg+xml"
        assert b"<svg" in response.content

    def test_not_found(self, client):
        url = reverse("web:notice-board:encounter-qr", kwargs={"share_code": "XXXXXX"})

        response = client.get(url)

        assert_response_404(response)
