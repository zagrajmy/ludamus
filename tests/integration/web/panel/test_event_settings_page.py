from http import HTTPStatus
from unittest.mock import ANY, patch

import pytest
from django.contrib import messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from ludamus.pacts import EventDTO, NotFoundError
from tests.integration.conftest import EventFactory
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


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

    def test_inherit_label_reflects_sphere_default_disallowed(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        sphere.allow_facilitator_session_edit = False
        sphere.save()

        response = authenticated_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        edit_field = response.context["form"].fields["allow_facilitator_session_edit"]
        assert "disallowed" in dict(edit_field.choices)[""]

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

    def test_uploads_logo(self, authenticated_client, active_user, sphere, event):
        sphere.managers.add(active_user)
        gif_bytes = (
            b"GIF89a\x01\x00\x01\x00\x80\x00\x00"
            b"\xff\xff\xff\x00\x00\x00!\xf9\x04\x00\x00\x00\x00\x00"
            b",\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
        )
        logo = SimpleUploadedFile("logo.gif", gif_bytes, content_type="image/gif")

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
            HTTPStatus.FOUND,
            messages=[
                (messages.ERROR, "Event name is required."),
                (messages.ERROR, "Event slug is required."),
                (messages.ERROR, "Start time is required."),
                (messages.ERROR, "End time is required."),
            ],
            url=f"/panel/event/{event.slug}/settings/",
        )
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
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event name is too long (max 255 characters).")],
            url=f"/panel/event/{event.slug}/settings/",
        )
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
