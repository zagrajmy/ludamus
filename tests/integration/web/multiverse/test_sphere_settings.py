from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse

from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the sphere panel."

TAB_URLS = {
    "general": "/multiverse/panel/",
    "connections": "/multiverse/panel/connections/",
}
GENERAL_PANEL_CONTEXT = {
    "events": [],
    "current_event": None,
    "is_proposal_active": False,
    "active_nav": "sphere-settings",
    "is_general_tab": True,
    "is_connections_tab": False,
    "tab_urls": TAB_URLS,
    "form": ANY,
}


class TestSphereSettingsPageView:
    """Tests for /multiverse/panel/ (sphere settings — general tab)."""

    url = reverse("multiverse:panel:sphere-settings")

    def test_get_redirects_anonymous_user_to_login(self, client):
        response = client.get(self.url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={self.url}"
        )

    def test_get_redirects_non_manager_user(self, authenticated_client):
        response = authenticated_client.get(self.url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_get_ok_for_sphere_manager(self, authenticated_client, active_user, sphere):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.url)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/sphere-settings.html",
            context_data=GENERAL_PANEL_CONTEXT,
        )

    def test_post_persists_disallow(self, authenticated_client, active_user, sphere):
        sphere.managers.add(active_user)
        sphere.allow_facilitator_session_edit = True
        sphere.save()

        response = authenticated_client.post(self.url, data={})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Sphere settings saved successfully.")],
            url=self.url,
        )
        sphere.refresh_from_db()
        assert sphere.allow_facilitator_session_edit is False

    def test_post_persists_allow(self, authenticated_client, active_user, sphere):
        sphere.managers.add(active_user)
        sphere.allow_facilitator_session_edit = False
        sphere.save()

        response = authenticated_client.post(
            self.url, data={"allow_facilitator_session_edit": "on"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Sphere settings saved successfully.")],
            url=self.url,
        )
        sphere.refresh_from_db()
        assert sphere.allow_facilitator_session_edit is True

    def test_post_rejects_non_manager(self, authenticated_client, sphere):
        sphere.allow_facilitator_session_edit = True
        sphere.save()

        response = authenticated_client.post(
            self.url, data={"allow_facilitator_session_edit": "on"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )
        sphere.refresh_from_db()
        assert sphere.allow_facilitator_session_edit is True
