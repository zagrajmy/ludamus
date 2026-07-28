from http import HTTPStatus
from unittest.mock import ANY

from django.urls import reverse

from tests.integration.utils import assert_response


class TestAuthErrorPageView:
    URL = reverse("web:auth-error")

    def test_ok(self, client):
        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=["crowd/auth_error.html"],
            context_data={"view": ANY, "tracking": ""},
        )

    def test_ok_with_auth0_error_params(self, client):
        response = client.get(
            self.URL,
            {
                "client_id": "",
                "connection": "",
                "lang": "",
                "error": "invalid_request",
                "error_description": "We couldn't find your session.",
                "tracking": "d9bd4fc6d133caf8b064",
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=["crowd/auth_error.html"],
            context_data={"view": ANY, "tracking": "d9bd4fc6d133caf8b064"},
        )

    def test_ok_caps_overlong_tracking_value(self, client):
        response = client.get(self.URL, {"tracking": "x" * 500})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=["crowd/auth_error.html"],
            context_data={"view": ANY, "tracking": "x" * 64},
        )
