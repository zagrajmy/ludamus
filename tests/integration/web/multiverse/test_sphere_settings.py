from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.contrib import messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from tests.integration.conftest import PNG_BYTES
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the sphere panel."

SVG_BYTES = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
    b'<rect width="10" height="10" fill="#123"/></svg>'
)

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

    @pytest.mark.usefixtures("panel_access_user")
    def test_get_ok_for_manager_and_superuser(self, authenticated_client):
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
        logo = SimpleUploadedFile("brand.png", PNG_BYTES, content_type="image/png")

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

    def test_post_uploads_svg_logo(self, authenticated_client, active_user, sphere):
        sphere.managers.add(active_user)
        logo = SimpleUploadedFile("brand.svg", SVG_BYTES, content_type="image/svg+xml")

        response = authenticated_client.post(self.url, data={"logo": logo})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Sphere settings saved successfully.")],
            url=self.url,
        )
        sphere.refresh_from_db()
        assert sphere.logo.name.startswith("spheres/")
        assert sphere.logo.name.endswith(".svg")

    def test_post_svg_logo_with_script_is_rejected(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        malicious = SVG_BYTES.replace(b"</svg>", b"<script>alert(1)</script></svg>")
        logo = SimpleUploadedFile("evil.svg", malicious, content_type="image/svg+xml")

        response = authenticated_client.post(self.url, data={"logo": logo})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Invalid or unsafe SVG file.")],
            url=self.url,
        )
        sphere.refresh_from_db()
        assert not sphere.logo

    def test_post_svg_logo_with_event_handler_is_rejected(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        malicious = SVG_BYTES.replace(b"<rect ", b'<rect onload="alert(1)" ')
        logo = SimpleUploadedFile("evil.svg", malicious, content_type="image/svg+xml")

        response = authenticated_client.post(self.url, data={"logo": logo})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Invalid or unsafe SVG file.")],
            url=self.url,
        )
        sphere.refresh_from_db()
        assert not sphere.logo

    def test_post_logo_too_large_is_rejected(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        oversized = PNG_BYTES + b"\x00" * (8 * 1024 * 1024 + 1)
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
