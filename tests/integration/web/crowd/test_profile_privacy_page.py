from http import HTTPStatus

from django.urls import reverse

from tests.integration.utils import assert_response


class TestProfilePrivacyPageView:
    URL = reverse("web:crowd:profile-privacy")

    def test_unauthenticated_redirects(self, client):
        response = client.get(self.URL)

        assert response.status_code == HTTPStatus.FOUND

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
