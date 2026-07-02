import io
from http import HTTPStatus
from unittest.mock import ANY, patch

import pytest
from django.contrib import messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from ludamus.pacts import EventDTO, NotFoundError
from tests.integration.conftest import EventFactory
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."
PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01"
    b"\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
)
GIF_BYTES = bytes.fromhex(
    "47494638376101000100810000ffffff0000000000000000002c000000000100"
    "010000080400010404003b"
)


class TestEventSettingsPageViewGet:
    @staticmethod
    def get_url(event):
        return reverse("panel:event-settings", kwargs={"slug": event.slug})

    def test_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_ok_for_sphere_manager(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/settings.html",
            context_data={
                "current_event": EventDTO.model_validate(event),
                "events": [EventDTO.model_validate(event)],
                "is_proposal_active": response.context["is_proposal_active"],
                "stats": {
                    "hosts_count": 0,
                    "pending_proposals": 0,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 0,
                    "total_sessions": 0,
                },
                "active_nav": "settings",
                "active_tab": "general",
                "tab_urls": response.context["tab_urls"],
                "form": ANY,
            },
        )

    def test_shows_existing_logo_preview(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        event.logo = "events/brand.png"
        event.save()

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/settings.html",
            context_data=ANY,
        )
        assert "events/brand.png" in response.content.decode()

    def test_inherit_label_reflects_sphere_default_disallowed(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        sphere.allow_facilitator_session_edit = False
        sphere.save()

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/settings.html",
            context_data=ANY,
        )
        edit_field = response.context["form"].fields["allow_facilitator_session_edit"]
        assert "disallowed" in dict(edit_field.choices)[""]

    def test_form_initial_uses_false_when_event_disallows_edits(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        event.allow_facilitator_session_edit = False
        event.save()

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/settings.html",
            context_data=ANY,
        )
        assert (
            response.context["form"].initial["allow_facilitator_session_edit"]
            == "false"
        )

    def test_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse("panel:event-settings", kwargs={"slug": "nonexistent"})

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    @pytest.mark.usefixtures("event")
    def test_can_view_different_events(
        self, authenticated_client, active_user, sphere, faker
    ):
        sphere.managers.add(active_user)
        event2 = EventFactory(sphere=sphere, slug=faker.slug())

        response = authenticated_client.get(self.get_url(event2))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/settings.html",
            context_data={
                "current_event": EventDTO.model_validate(event2),
                "events": response.context["events"],
                "is_proposal_active": response.context["is_proposal_active"],
                "stats": {
                    "hosts_count": 0,
                    "pending_proposals": 0,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 0,
                    "total_sessions": 0,
                },
                "active_nav": "settings",
                "active_tab": "general",
                "tab_urls": response.context["tab_urls"],
                "form": ANY,
            },
        )


class TestEventSettingsPageViewPost:
    @staticmethod
    def get_url(event):
        return reverse("panel:event-settings", kwargs={"slug": event.slug})

    @staticmethod
    def _post_data(event, **overrides):
        data = {
            "name": event.name,
            "slug": event.slug,
            "start_time": event.start_time.strftime("%Y-%m-%dT%H:%M"),
            "end_time": event.end_time.strftime("%Y-%m-%dT%H:%M"),
        }
        data.update(overrides)
        return data

    @staticmethod
    def _render_context(response, event):
        return {
            "current_event": EventDTO.model_validate(event),
            "events": response.context["events"],
            "is_proposal_active": response.context["is_proposal_active"],
            "stats": {
                "hosts_count": 0,
                "pending_proposals": 0,
                "rooms_count": 0,
                "scheduled_sessions": 0,
                "total_proposals": 0,
                "total_sessions": 0,
            },
            "active_nav": "settings",
            "active_tab": "general",
            "tab_urls": response.context["tab_urls"],
            "form": ANY,
        }

    def test_redirects_anonymous_user(self, client, event):
        url = self.get_url(event)

        response = client.post(url, data=self._post_data(event, name="New Name"))

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.post(
            self.get_url(event), data=self._post_data(event, name="New Name")
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse("panel:event-settings", kwargs={"slug": "nonexistent"})

        response = authenticated_client.post(url, data={"name": "New Name"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_updates_event_name(
        self, authenticated_client, active_user, sphere, event, faker
    ):
        sphere.managers.add(active_user)
        new_name = faker.sentence(nb_words=3)

        response = authenticated_client.post(
            self.get_url(event), data=self._post_data(event, name=new_name)
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Event settings saved successfully.")],
            url=f"/panel/event/{event.slug}/settings/",
        )
        event.refresh_from_db()
        assert event.name == new_name

    def test_updates_cover_image(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        image = SimpleUploadedFile("cover.png", PNG_BYTES, content_type="image/png")

        response = authenticated_client.post(
            self.get_url(event), data={**self._post_data(event), "cover_image": image}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Event settings saved successfully.")],
            url=f"/panel/event/{event.slug}/settings/",
        )
        event.refresh_from_db()
        assert event.cover_image
        assert event.cover_image_url.startswith("/media/events/")

    def test_updates_session_cover_placeholder_setting(
        self, *, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        assert not event.use_session_cover_placeholders

        response = authenticated_client.post(
            self.get_url(event),
            data={**self._post_data(event), "use_session_cover_placeholders": "on"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Event settings saved successfully.")],
            url=f"/panel/event/{event.slug}/settings/",
        )
        event.refresh_from_db()
        assert event.use_session_cover_placeholders

    def test_removes_cover_image(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        event.cover_image = SimpleUploadedFile(
            "cover.png", PNG_BYTES, content_type="image/png"
        )
        event.save()
        storage = event.cover_image.storage
        old_name = event.cover_image.name

        response = authenticated_client.post(
            self.get_url(event),
            data={**self._post_data(event), "cover_image-clear": "on"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Event settings saved successfully.")],
            url=f"/panel/event/{event.slug}/settings/",
        )
        event.refresh_from_db()
        assert not event.cover_image
        assert not storage.exists(old_name)

    def test_cover_replacement_survives_storage_cleanup_failure(
        self, authenticated_client, active_user, sphere, event, caplog
    ):
        sphere.managers.add(active_user)
        event.cover_image = SimpleUploadedFile(
            "old.png", PNG_BYTES, content_type="image/png"
        )
        event.save()
        new_image = SimpleUploadedFile("new.png", PNG_BYTES, content_type="image/png")

        with (
            patch.object(
                event.cover_image.storage, "delete", side_effect=OSError("boom")
            ),
            caplog.at_level("WARNING", logger="ludamus.links.db.django.repositories"),
        ):
            response = authenticated_client.post(
                self.get_url(event),
                data={**self._post_data(event), "cover_image": new_image},
            )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Event settings saved successfully.")],
            url=f"/panel/event/{event.slug}/settings/",
        )
        event.refresh_from_db()
        assert event.cover_image
        assert "Best-effort cleanup" in caplog.text

    def test_rejects_oversize_cover_dimensions(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        buffer = io.BytesIO()
        Image.new("RGB", (5000, 5000)).save(buffer, format="PNG")
        image = SimpleUploadedFile(
            "huge.png", buffer.getvalue(), content_type="image/png"
        )

        response = authenticated_client.post(
            self.get_url(event), data={**self._post_data(event), "cover_image": image}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=self._render_context(response, event),
            template_name="panel/settings.html",
        )
        assert response.context["form"].errors["cover_image"] == [
            "Image dimensions are too large."
        ]
        event.refresh_from_db()
        assert not event.cover_image

    def test_rejects_too_large_cover_image(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        image = SimpleUploadedFile(
            "cover.png",
            PNG_BYTES + b"0" * (8 * 1024 * 1024 + 1),
            content_type="image/png",
        )

        response = authenticated_client.post(
            self.get_url(event), data={**self._post_data(event), "cover_image": image}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=self._render_context(response, event),
            template_name="panel/settings.html",
        )
        assert response.context["form"].errors["cover_image"] == [
            "Image too large. Maximum size is 8 MB."
        ]
        event.refresh_from_db()
        assert not event.cover_image

    def test_rejects_unsupported_cover_image_format(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        image = SimpleUploadedFile("cover.gif", GIF_BYTES, content_type="image/gif")

        response = authenticated_client.post(
            self.get_url(event), data={**self._post_data(event), "cover_image": image}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=self._render_context(response, event),
            template_name="panel/settings.html",
        )
        assert response.context["form"].errors["cover_image"] == [
            "Unsupported image format. Use JPG, PNG, WebP, or AVIF."
        ]
        event.refresh_from_db()
        assert not event.cover_image

    def test_uploads_logo(self, authenticated_client, active_user, sphere, event):
        sphere.managers.add(active_user)
        logo = SimpleUploadedFile("logo.png", PNG_BYTES, content_type="image/png")

        response = authenticated_client.post(
            self.get_url(event), data=self._post_data(event, logo=logo)
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Event settings saved successfully.")],
            url=f"/panel/event/{event.slug}/settings/",
        )
        event.refresh_from_db()
        assert event.logo
        assert event.logo.name.startswith("events/")

    def test_rejects_too_large_logo(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        logo = SimpleUploadedFile(
            "logo.png",
            PNG_BYTES + b"0" * (8 * 1024 * 1024 + 1),
            content_type="image/png",
        )

        response = authenticated_client.post(
            self.get_url(event), data=self._post_data(event, logo=logo)
        )

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=self._render_context(response, event),
            template_name="panel/settings.html",
        )
        assert response.context["form"].errors["logo"] == [
            "Image too large. Maximum size is 8 MB."
        ]
        event.refresh_from_db()
        assert not event.logo

    def test_save_without_logo_keeps_existing(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        event.logo = "events/keep.png"
        event.save()

        response = authenticated_client.post(
            self.get_url(event), data=self._post_data(event, name="Renamed")
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Event settings saved successfully.")],
            url=f"/panel/event/{event.slug}/settings/",
        )
        event.refresh_from_db()
        assert event.logo.name == "events/keep.png"

    def test_error_on_empty_form(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        original_name = event.name

        response = authenticated_client.post(self.get_url(event), data={})

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=self._render_context(response, event),
            template_name="panel/settings.html",
        )
        form_errors = response.context["form"].errors
        assert form_errors["name"] == ["Event name is required."]
        assert form_errors["slug"] == ["Event slug is required."]
        assert form_errors["start_time"] == ["Start time is required."]
        assert form_errors["end_time"] == ["End time is required."]
        event.refresh_from_db()
        assert event.name == original_name

    def test_error_on_name_too_long(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        original_name = event.name
        long_name = "x" * 256

        response = authenticated_client.post(
            self.get_url(event), data=self._post_data(event, name=long_name)
        )

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=self._render_context(response, event),
            template_name="panel/settings.html",
        )
        assert response.context["form"].errors["name"] == [
            "Event name is too long (max 255 characters)."
        ]
        event.refresh_from_db()
        assert event.name == original_name

    def test_error_event_not_found_during_update(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        with patch(
            "ludamus.links.db.django.repositories.EventRepository.update",
            side_effect=NotFoundError,
        ):
            response = authenticated_client.post(
                self.get_url(event), data=self._post_data(event, name="New Name")
            )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url=f"/panel/event/{event.slug}/settings/",
        )

    def test_error_on_duplicate_slug(
        self, authenticated_client, active_user, sphere, event, faker
    ):
        sphere.managers.add(active_user)
        other_event = EventFactory(sphere=sphere, slug=faker.slug())
        original_slug = event.slug

        response = authenticated_client.post(
            self.get_url(event), data=self._post_data(event, slug=other_event.slug)
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "An event with this slug already exists.")],
            url=f"/panel/event/{original_slug}/settings/",
        )
        event.refresh_from_db()
        assert event.slug == original_slug

    def test_updates_event_slug(
        self, authenticated_client, active_user, sphere, event, faker
    ):
        sphere.managers.add(active_user)
        new_slug = faker.slug()

        response = authenticated_client.post(
            self.get_url(event), data=self._post_data(event, slug=new_slug)
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Event settings saved successfully.")],
            url=f"/panel/event/{new_slug}/settings/",
        )
        event.refresh_from_db()
        assert event.slug == new_slug

    def test_sets_facilitator_edit_override_allow(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            self.get_url(event),
            data=self._post_data(event, allow_facilitator_session_edit="true"),
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Event settings saved successfully.")],
            url=f"/panel/event/{event.slug}/settings/",
        )
        event.refresh_from_db()
        assert event.allow_facilitator_session_edit is True

    def test_sets_facilitator_edit_override_disallow(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            self.get_url(event),
            data=self._post_data(event, allow_facilitator_session_edit="false"),
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Event settings saved successfully.")],
            url=f"/panel/event/{event.slug}/settings/",
        )
        event.refresh_from_db()
        assert event.allow_facilitator_session_edit is False

    def test_sets_facilitator_edit_override_inherit(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        event.allow_facilitator_session_edit = False
        event.save()

        response = authenticated_client.post(
            self.get_url(event),
            data=self._post_data(event, allow_facilitator_session_edit=""),
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Event settings saved successfully.")],
            url=f"/panel/event/{event.slug}/settings/",
        )
        event.refresh_from_db()
        assert event.allow_facilitator_session_edit is None

    def test_enables_auto_confirm_sessions(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        event.auto_confirm_sessions = False
        event.save()

        response = authenticated_client.post(
            self.get_url(event), data=self._post_data(event, auto_confirm_sessions="on")
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Event settings saved successfully.")],
            url=f"/panel/event/{event.slug}/settings/",
        )
        event.refresh_from_db()
        assert event.auto_confirm_sessions is True

    def test_disables_auto_confirm_sessions_when_unchecked(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            self.get_url(event), data=self._post_data(event)
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Event settings saved successfully.")],
            url=f"/panel/event/{event.slug}/settings/",
        )
        event.refresh_from_db()
        assert event.auto_confirm_sessions is False

    def test_enables_participants_label(
        self, *, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        assert event.use_participants_label is False

        response = authenticated_client.post(
            self.get_url(event),
            data=self._post_data(event, use_participants_label="on"),
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Event settings saved successfully.")],
            url=f"/panel/event/{event.slug}/settings/",
        )
        event.refresh_from_db()
        assert event.use_participants_label is True

    def test_disables_participants_label_when_unchecked(
        self, *, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        event.use_participants_label = True
        event.save()

        response = authenticated_client.post(
            self.get_url(event), data=self._post_data(event)
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Event settings saved successfully.")],
            url=f"/panel/event/{event.slug}/settings/",
        )
        event.refresh_from_db()
        assert event.use_participants_label is False
