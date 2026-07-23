from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from tests.integration.utils import assert_response

_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01"
    b"\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
)

PERMISSION_ERROR = "You don't have permission to access the sphere panel."

TAB_URLS = {
    "general": "/multiverse/panel/",
    "connections": "/multiverse/panel/connections/",
    "announcements": "/multiverse/panel/announcements/",
    "mcp": "/multiverse/panel/mcp/",
}
GENERAL_PANEL_CONTEXT = {
    "events": [],
    "current_event": None,
    "is_proposal_active": False,
    "active_nav": "sphere-settings",
    "active_tab": "general",
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

    def test_get_ok_for_superuser_non_manager(self, authenticated_client, active_user):
        active_user.is_superuser = True
        active_user.save()

        response = authenticated_client.get(self.url)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/sphere-settings.html",
            context_data=GENERAL_PANEL_CONTEXT,
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

    def test_get_shows_existing_logo_preview(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        sphere.logo = "spheres/brand.png"
        sphere.save()

        response = authenticated_client.get(self.url)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/sphere-settings.html",
            context_data=GENERAL_PANEL_CONTEXT,
        )
        assert "spheres/brand.png" in response.content.decode()

    def test_post_uploads_logo(self, authenticated_client, active_user, sphere):
        sphere.managers.add(active_user)
        logo = SimpleUploadedFile("brand.png", _PNG_BYTES, content_type="image/png")

        response = authenticated_client.post(self.url, data={"logo": logo})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Sphere settings saved successfully.")],
            url=self.url,
        )
        sphere.refresh_from_db()
        assert sphere.logo
        assert sphere.logo.name.startswith("spheres/")

    def test_post_logo_too_large_is_rejected(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        oversized = _PNG_BYTES + b"\x00" * (8 * 1024 * 1024 + 1)
        logo = SimpleUploadedFile("big.png", oversized, content_type="image/png")

        response = authenticated_client.post(self.url, data={"logo": logo})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Image too large. Maximum size is 8 MB.")],
            url=self.url,
        )

    def test_post_without_logo_keeps_existing(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        sphere.logo = "spheres/keep.png"
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
        assert sphere.logo.name == "spheres/keep.png"

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
