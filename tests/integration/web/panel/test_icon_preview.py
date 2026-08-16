from http import HTTPStatus

from django.test import override_settings
from django.urls import reverse

from tests.integration.utils import assert_login_required
from tests.integration.web.panel.helpers import assert_not_a_manager

URL = reverse("panel:icon-preview")


class TestIconPreviewPartView:
    def test_valid_icon_returns_svg(self, panel_client):
        response = panel_client.get(URL, data={"icon": "star"})

        assert response.status_code == HTTPStatus.OK
        assert b"<svg" in response.content

    def test_invalid_icon_returns_empty(self, panel_client):
        response = panel_client.get(URL, data={"icon": "not-a-real-icon"})

        assert response.status_code == HTTPStatus.OK
        assert b"<svg" not in response.content

    @override_settings(DEBUG=True)
    def test_invalid_icon_returns_empty_in_debug_mode(self, panel_client):
        response = panel_client.get(URL, data={"icon": "not-a-real-icon"})

        assert response.status_code == HTTPStatus.OK
        assert response.content == b""

    def test_empty_icon_param_returns_empty(self, panel_client):
        response = panel_client.get(URL, data={"icon": ""})

        assert response.status_code == HTTPStatus.OK
        assert response.content == b""

    def test_missing_icon_param_returns_empty(self, panel_client):
        response = panel_client.get(URL)

        assert response.status_code == HTTPStatus.OK
        assert response.content == b""

    def test_redirects_anonymous_user(self, client):
        response = client.get(URL)

        assert_login_required(response, URL)

    def test_redirects_non_manager_user(self, authenticated_client):
        response = authenticated_client.get(URL)

        assert_not_a_manager(response)
