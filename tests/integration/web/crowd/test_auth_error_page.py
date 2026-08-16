from http import HTTPStatus

from django.urls import reverse

from tests.integration.utils import assert_response


class TestAuthErrorPage:
    URL = reverse("web:auth-error")

    def test_ok(self, client):
        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="crowd/auth_error.html",
            context_data={"tracking": ""},
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
            template_name="crowd/auth_error.html",
            context_data={"tracking": "d9bd4fc6d133caf8b064"},
        )

    def test_ok_drops_tracking_that_is_not_a_token(self, client):
        response = client.get(self.URL, {"tracking": "call +48 123, urgent!"})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="crowd/auth_error.html",
            context_data={"tracking": ""},
        )

    def test_ok_drops_overlong_tracking_value(self, client):
        response = client.get(self.URL, {"tracking": "x" * 65})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="crowd/auth_error.html",
            context_data={"tracking": ""},
        )

    def test_logs_vetted_params_and_blanks_junk(self, client, caplog):
        with caplog.at_level("WARNING", logger="ludamus.gates.web.django.auth_pages"):
            client.get(
                self.URL,
                {"error": "invalid request!", "tracking": "d9bd4fc6d133caf8b064"},
            )

        assert "Auth0 error redirect: error=- tracking=d9bd4fc6d133caf8b064" in (
            caplog.text
        )

    def test_param_less_visit_logs_nothing(self, client, caplog):
        with caplog.at_level("WARNING", logger="ludamus.gates.web.django.auth_pages"):
            client.get(self.URL)

        assert "Auth0 error redirect" not in caplog.text
