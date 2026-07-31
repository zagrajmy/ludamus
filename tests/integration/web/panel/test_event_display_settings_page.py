from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import EventSettings, SessionField
from tests.integration.utils import assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_login_required,
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
            context_data={
                **panel_context(event, active_nav="settings"),
                "is_proposal_active": response.context["is_proposal_active"],
                "active_tab": "display",
                "tab_urls": response.context["tab_urls"],
                "fields": [],
                "filterable_field_ids": [],
            },
        )

    def test_shows_session_fields(self, panel_client, event):
        field = _create_session_field(event)

        response = panel_client.get(self.get_url(event))

        assert len(response.context["fields"]) == 1
        assert response.context["fields"][0].pk == field.pk

    def test_excludes_non_public_fields(self, panel_client, event):
        _create_session_field(event, name="Public", slug="public", is_public=True)
        _create_session_field(event, name="Private", slug="private", is_public=False)

        response = panel_client.get(self.get_url(event))

        field_names = [f.name for f in response.context["fields"]]
        assert field_names == ["Public"]

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

    def test_clears_filterable_fields(self, panel_client, event):
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
