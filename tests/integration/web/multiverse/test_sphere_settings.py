import io
from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.contrib import messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image as PILImage

from ludamus.pacts import EventDTO
from tests.integration.conftest import PNG_BYTES, EncounterFactory
from tests.integration.utils import assert_login_required, assert_response
from tests.integration.web.multiverse.helpers import (
    assert_not_a_sphere_manager,
    sphere_settings_context,
)

SVG_BYTES = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
    b'<rect width="10" height="10" fill="#123"/></svg>'
)
XML_BOMB_BYTES = (
    b'<?xml version="1.0"?><!DOCTYPE svg ['
    b'<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
    b'<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">'
    b'<!ENTITY d "&c;&c;&c;&c;&c;&c;&c;&c;&c;&c;">'
    b'<!ENTITY e "&d;&d;&d;&d;&d;&d;&d;&d;&d;&d;">'
    b'<!ENTITY f "&e;&e;&e;&e;&e;&e;&e;&e;&e;&e;">]>'
    b'<svg xmlns="http://www.w3.org/2000/svg"><text>&f;</text></svg>'
)
GIF_BYTES = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!"
    b"\xf9\x04\x00\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00"
    b"\x02\x02D\x01\x00;"
)

GENERAL_PANEL_CONTEXT = sphere_settings_context(active_tab="general") | {
    "form": ANY,
    "disable_warning_pages": [],
    "needs_disable_confirmation": False,
    "confirmed_page_disable": "",
}

PAGE_DATA = {
    "enabled_pages": ["events", "encounters"],
    "default_page": "events",
    "encounter_public_policy": "disabled",
}

SETTINGS_TEMPLATE = "multiverse/panel/sphere-settings.html"


def assert_form_error(response, *field_errors):
    # An invalid submit re-renders the bound form rather than redirecting, so
    # the manager keeps every other edit. `contains` because the subject is the
    # copy the manager reads, which lives inside the form, not in the context.
    assert_response(
        response,
        HTTPStatus.OK,
        template_name=SETTINGS_TEMPLATE,
        context_data=GENERAL_PANEL_CONTEXT,
        contains=field_errors,
    )


class TestSphereSettingsPageView:
    """Tests for /multiverse/panel/ (sphere settings — general tab)."""

    url = reverse("multiverse:panel:sphere-settings")

    def test_get_redirects_anonymous_user_to_login(self, client):
        response = client.get(self.url)

        assert_login_required(response, self.url)

    def test_get_redirects_non_manager_user(self, authenticated_client):
        response = authenticated_client.get(self.url)

        assert_not_a_sphere_manager(response)

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

        response = authenticated_client.post(self.url, data=PAGE_DATA)

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
            self.url, data=PAGE_DATA | {"allow_facilitator_session_edit": "on"}
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

        response = authenticated_client.post(self.url, data=PAGE_DATA | {"logo": logo})

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

        response = authenticated_client.post(self.url, data=PAGE_DATA | {"logo": logo})

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

        response = authenticated_client.post(self.url, data=PAGE_DATA | {"logo": logo})

        assert_form_error(response, "Invalid or unsafe SVG file.")
        sphere.refresh_from_db()
        assert not sphere.logo

    def test_post_svg_logo_with_event_handler_is_rejected(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        malicious = SVG_BYTES.replace(b"<rect ", b'<rect onload="alert(1)" ')
        logo = SimpleUploadedFile("evil.svg", malicious, content_type="image/svg+xml")

        response = authenticated_client.post(self.url, data=PAGE_DATA | {"logo": logo})

        assert_form_error(response, "Invalid or unsafe SVG file.")
        sphere.refresh_from_db()
        assert not sphere.logo

    @pytest.mark.parametrize(
        "malicious",
        (
            SVG_BYTES.replace(b"<rect", b'<a href="javascript:alert(1)"><rect').replace(
                b"</svg>", b"</a></svg>"
            ),
            SVG_BYTES[:-10],
            b'<not-svg xmlns="http://www.w3.org/2000/svg"/>',
            XML_BOMB_BYTES,
        ),
        ids=["javascript-url", "malformed-xml", "non-svg-root", "xml-bomb"],
    )
    def test_post_bad_svg_logo_is_rejected(
        self, authenticated_client, active_user, sphere, malicious
    ):
        sphere.managers.add(active_user)
        logo = SimpleUploadedFile("evil.svg", malicious, content_type="image/svg+xml")

        response = authenticated_client.post(self.url, data=PAGE_DATA | {"logo": logo})

        assert_form_error(response, "Invalid or unsafe SVG file.")
        sphere.refresh_from_db()
        assert not sphere.logo

    @pytest.mark.parametrize(
        ("content", "filename"),
        ((b"\x89PNG but not really", "broken.png"), (GIF_BYTES, "anim.gif")),
        ids=["undecodable", "disallowed-format"],
    )
    def test_post_non_svg_logo_with_bad_format_is_rejected(
        self, authenticated_client, active_user, sphere, content, filename
    ):
        sphere.managers.add(active_user)
        logo = SimpleUploadedFile(filename, content, content_type="image/gif")

        response = authenticated_client.post(self.url, data=PAGE_DATA | {"logo": logo})

        assert_form_error(
            response, "Unsupported image format. Use JPG, PNG, WebP, AVIF, or SVG."
        )
        sphere.refresh_from_db()
        assert not sphere.logo

    def test_post_logo_with_huge_dimensions_is_rejected(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        bomb = io.BytesIO()
        PILImage.new("1", (6000, 5000)).save(bomb, "PNG")
        logo = SimpleUploadedFile("bomb.png", bomb.getvalue(), content_type="image/png")

        response = authenticated_client.post(self.url, data=PAGE_DATA | {"logo": logo})

        assert_form_error(response, "Image dimensions are too large.")
        sphere.refresh_from_db()
        assert not sphere.logo

    def test_post_logo_too_large_is_rejected(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        oversized = PNG_BYTES + b"\x00" * (8 * 1024 * 1024 + 1)
        logo = SimpleUploadedFile("big.png", oversized, content_type="image/png")

        response = authenticated_client.post(self.url, data=PAGE_DATA | {"logo": logo})

        assert_form_error(response, "Image too large. Maximum size is 8 MB.")

    def test_post_with_clear_checkbox_removes_logo(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        sphere.logo = "spheres/drop-me.png"
        sphere.save()

        response = authenticated_client.post(
            self.url, data=PAGE_DATA | {"logo-clear": "on"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Sphere settings saved successfully.")],
            url=self.url,
        )
        sphere.refresh_from_db()
        assert not sphere.logo

    def test_post_without_logo_keeps_existing(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        sphere.logo = "spheres/keep.png"
        sphere.save()

        response = authenticated_client.post(
            self.url, data=PAGE_DATA | {"allow_facilitator_session_edit": "on"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Sphere settings saved successfully.")],
            url=self.url,
        )
        sphere.refresh_from_db()
        assert sphere.logo.name == "spheres/keep.png"

    def test_post_persists_pages_and_policy(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            self.url,
            data={
                "enabled_pages": ["encounters"],
                "default_page": "encounters",
                "encounter_public_policy": "managers",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Sphere settings saved successfully.")],
            url=self.url,
        )
        sphere.refresh_from_db()
        assert sphere.enabled_pages == ["encounters"]
        assert sphere.default_page == "encounters"
        assert sphere.encounter_public_policy == "managers"

    def test_post_persists_timeline_as_default(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            self.url,
            data=PAGE_DATA
            | {"enabled_pages": ["timeline"], "default_page": "timeline"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Sphere settings saved successfully.")],
            url=self.url,
        )
        sphere.refresh_from_db()
        assert sphere.enabled_pages == ["timeline"]
        assert sphere.default_page == "timeline"

    @pytest.mark.parametrize("policy", ("disabled", "managers", "everyone"))
    def test_post_persists_each_policy(
        self, authenticated_client, active_user, sphere, policy
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            self.url, data=PAGE_DATA | {"encounter_public_policy": policy}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Sphere settings saved successfully.")],
            url=self.url,
        )
        sphere.refresh_from_db()
        assert sphere.encounter_public_policy == policy

    def test_post_rejects_default_page_not_enabled(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            self.url, data=PAGE_DATA | {"enabled_pages": ["encounters"]}
        )

        assert_form_error(
            response, "The default page must be one of the enabled pages."
        )
        sphere.refresh_from_db()
        assert sphere.enabled_pages == ["events", "encounters", "timeline"]

    def test_post_rejects_no_enabled_pages(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            self.url,
            data={"default_page": "events", "encounter_public_policy": "disabled"},
        )

        assert_form_error(
            response,
            "At least one page must stay enabled.",
            "The default page must be one of the enabled pages.",
        )
        sphere.refresh_from_db()
        assert sphere.enabled_pages == ["events", "encounters", "timeline"]

    def test_post_disabling_page_with_content_asks_for_confirmation(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        EncounterFactory(sphere=sphere)

        response = authenticated_client.post(
            self.url, data=PAGE_DATA | {"enabled_pages": ["events"]}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=SETTINGS_TEMPLATE,
            context_data=GENERAL_PANEL_CONTEXT
            | {
                "disable_warning_pages": ["Encounters", "Timeline"],
                "needs_disable_confirmation": True,
                "confirmed_page_disable": "encounters,timeline",
            },
        )
        sphere.refresh_from_db()
        assert sphere.enabled_pages == ["events", "encounters", "timeline"]

    def test_post_disabling_page_with_content_confirmed_saves(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        EncounterFactory(sphere=sphere)

        response = authenticated_client.post(
            self.url,
            data=PAGE_DATA
            | {
                "enabled_pages": ["events"],
                "confirmed_page_disable": "encounters,timeline",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Sphere settings saved successfully.")],
            url=self.url,
        )
        sphere.refresh_from_db()
        assert sphere.enabled_pages == ["events"]

    def test_post_confirmation_does_not_carry_over_to_another_page(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        EncounterFactory(sphere=sphere)

        # Confirmed for Encounters, then Events is unticked instead: the
        # warning has to come back for the page nobody was warned about.
        response = authenticated_client.post(
            self.url,
            data=PAGE_DATA
            | {
                "enabled_pages": ["encounters"],
                "default_page": "encounters",
                "confirmed_page_disable": "encounters",
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=SETTINGS_TEMPLATE,
            context_data=GENERAL_PANEL_CONTEXT
            | {
                "events": [EventDTO.model_validate(event)],
                "current_event": EventDTO.model_validate(event),
                "disable_warning_pages": ["Events", "Timeline"],
                "needs_disable_confirmation": True,
                "confirmed_page_disable": "events,timeline",
            },
        )
        sphere.refresh_from_db()
        assert sphere.enabled_pages == ["events", "encounters", "timeline"]

    def test_post_disabling_empty_page_saves_without_confirmation(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            self.url,
            data=PAGE_DATA
            | {"enabled_pages": ["encounters"], "default_page": "encounters"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Sphere settings saved successfully.")],
            url=self.url,
        )
        sphere.refresh_from_db()
        assert sphere.enabled_pages == ["encounters"]

    def test_post_rejects_non_manager(self, authenticated_client, sphere):
        sphere.allow_facilitator_session_edit = True
        sphere.save()

        response = authenticated_client.post(
            self.url, data=PAGE_DATA | {"allow_facilitator_session_edit": "on"}
        )

        assert_not_a_sphere_manager(response)
        sphere.refresh_from_db()
        assert sphere.allow_facilitator_session_edit is True
