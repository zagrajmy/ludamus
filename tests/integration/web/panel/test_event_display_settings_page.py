from http import HTTPStatus

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.gates.web.django.panel import settings_tab_urls
from ludamus.links.db.django.models import EventSettings, SessionField
from ludamus.pacts.fields import OrganizerFieldDTO
from tests.integration.utils import assert_login_required, assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_not_a_manager,
    panel_context,
)


def _create_session_field(event, name="Test Field", slug="test-field", **kwargs):
    defaults = {"is_public": True}
    return SessionField.objects.create(
        event=event,
        name=name,
        slug=slug,
        question=f"What is {name}?",
        **(defaults | kwargs),
    )


def _expected_field(field):
    # Every column _create_session_field leaves at its model default is spelled
    # out, so a changed default can't slip through as an equal DTO.
    return OrganizerFieldDTO(
        allow_custom=False,
        field_type="text",
        help_text="",
        icon="",
        is_multiple=False,
        is_public=True,
        max_length=50,
        name=field.name,
        options=[],
        order=0,
        pk=field.pk,
        question=field.question,
        slug=field.slug,
    )


def _expected_context(event, *, fields):
    return {
        **panel_context(event, active_nav="settings"),
        "active_tab": "display",
        "tab_urls": settings_tab_urls(event.slug),
        "fields": fields,
        "filterable_field_ids": [],
    }


class TestEventDisplaySettingsPageViewGet:
    @staticmethod
    def get_url(event):
        return reverse("panel:event-display-settings", kwargs={"slug": event.slug})

    def test_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.get(url)

        assert_login_required(response, url)

    def test_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event))

        assert_not_a_manager(response)

    def test_ok_for_sphere_manager(self, panel_client, event):
        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/display-settings.html",
            context_data=_expected_context(event, fields=[]),
        )

    def test_shows_session_fields(self, panel_client, event):
        field = _create_session_field(event)

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/display-settings.html",
            context_data=_expected_context(event, fields=[_expected_field(field)]),
        )

    def test_excludes_non_public_fields(self, panel_client, event):
        public = _create_session_field(event, name="Public", slug="public")
        _create_session_field(event, name="Private", slug="private", is_public=False)

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/display-settings.html",
            context_data=_expected_context(event, fields=[_expected_field(public)]),
        )

    def test_redirects_on_invalid_slug(self, panel_client):
        url = reverse("panel:event-display-settings", kwargs={"slug": "bad-slug"})

        response = panel_client.get(url)

        assert_event_not_found(response)


class TestEventDisplaySettingsPageViewPost:
    @staticmethod
    def get_url(event):
        return reverse("panel:event-display-settings", kwargs={"slug": event.slug})

    def test_redirects_anonymous_user(self, client, event):
        url = self.get_url(event)

        response = client.post(url)

        assert_login_required(response, url)

    def test_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.post(self.get_url(event))

        assert_not_a_manager(response)

    def test_redirects_on_invalid_slug(self, panel_client):
        url = reverse("panel:event-display-settings", kwargs={"slug": "bad-slug"})

        response = panel_client.post(url)

        assert_event_not_found(response)

    def test_saves_filterable_fields(self, panel_client, event):
        field1 = _create_session_field(event, name="Field 1", slug="field-1")
        field2 = _create_session_field(event, name="Field 2", slug="field-2")

        response = panel_client.post(
            self.get_url(event),
            data={"displayed_session_fields": [str(field1.pk), str(field2.pk)]},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Display settings saved successfully.")],
            url=f"/panel/event/{event.slug}/settings/display/",
        )

        # Verify saved — reload via GET
        response = panel_client.get(self.get_url(event))
        assert set(response.context["filterable_field_ids"]) == {field1.pk, field2.pk}

    # "²" is `str.isdigit()` but not `int()`-parsable, so it must be rejected
    # by the guard rather than crashing the parse below it.
    @pytest.mark.parametrize("raw_id", ("abc", "²"))
    def test_rejects_non_numeric_field_ids(
        self, authenticated_client, active_user, sphere, event, raw_id
    ):
        sphere.managers.add(active_user)
        field = _create_session_field(event)
        settings, _ = EventSettings.objects.get_or_create(event=event)
        settings.displayed_session_fields.set([field.pk])

        response = authenticated_client.post(
            self.get_url(event), data={"displayed_session_fields": [raw_id]}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Invalid field selection.")],
            url=f"/panel/event/{event.slug}/settings/display/",
        )
        assert list(settings.displayed_session_fields.values_list("pk", flat=True)) == [
            field.pk
        ]

    def test_clears_filterable_fields(
        self, authenticated_client, active_user, sphere, event, panel_client
    ):
        sphere.managers.add(active_user)
        field = _create_session_field(event)

        # First set a field
        settings, _ = EventSettings.objects.get_or_create(event=event)
        settings.displayed_session_fields.set([field.pk])

        # Then clear via POST
        response = panel_client.post(self.get_url(event), data={})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Display settings saved successfully.")],
            url=f"/panel/event/{event.slug}/settings/display/",
        )

        response = panel_client.get(self.get_url(event))
        assert response.context["filterable_field_ids"] == []
