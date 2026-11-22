from http import HTTPStatus

import pytest
from django.urls import reverse

from ludamus.links.analytics import redaction
from tests.integration.utils import assert_response


class TestProfilePrivacyPageView:
    URL = reverse("user:profile-privacy")

    def test_unauthenticated_redirects(self, client):
        response = client.get(self.URL)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={self.URL}"
        )

    def test_get(self, authenticated_client):
        # The analytics on/off split lives in the template via the analytics
        # context processor; the rendered states are asserted in
        # tests/e2e/tests/profile.auth.spec.ts.
        response = authenticated_client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"profile_active_tab": "privacy"},
            template_name="user/user/privacy.html",
        )

    @pytest.mark.usefixtures("sixteen_plus_user")
    def test_get_sixteen_plus_without_analytics_configured(
        self, authenticated_client, settings
    ):
        settings.POSTHOG_API_KEY = ""

        response = authenticated_client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"profile_active_tab": "privacy"},
            template_name="user/user/privacy.html",
        )
        optional_features_available = response.context["optional_features_available"]
        posthog_config = response.context["posthog_config"]
        assert optional_features_available is True
        assert posthog_config is None

    @pytest.mark.usefixtures("sixteen_plus_user")
    def test_get_sixteen_plus_with_analytics_configured(
        self, authenticated_client, sixteen_plus_user, settings
    ):
        settings.POSTHOG_API_KEY = "phc_integration"

        response = authenticated_client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"profile_active_tab": "privacy"},
            template_name="user/user/privacy.html",
        )
        optional_features_available = response.context["optional_features_available"]
        posthog_config = response.context["posthog_config"]
        assert optional_features_available is True
        assert posthog_config == {
            "api_key": "phc_integration",
            "host": settings.POSTHOG_HOST,
            "user_id": f"test:{sixteen_plus_user.pk}",
            "privacy_revision": str(sixteen_plus_user.privacy_revision),
            "environment": "test",
            "redaction_rules": redaction.client_patterns(),
        }
