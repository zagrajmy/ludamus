from http import HTTPStatus

from django.urls import reverse

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
            template_name="crowd/user/privacy.html",
        )
