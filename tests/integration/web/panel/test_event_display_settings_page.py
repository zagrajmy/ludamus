from http import HTTPStatus

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.gates.web.django.panel import settings_tab_urls
from ludamus.links.db.django.models import SessionField
from ludamus.pacts.fields import OrganizerFieldDTO
from tests.integration.conftest import EventFactory
from tests.integration.utils import assert_login_required, assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_not_a_manager,
    panel_context,
)


def _create_session_field(event, name="Test Field", slug="test-field", **kwargs):
    defaults = {"is_public": True, "field_type": "select"}
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
        field_type="select",
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
        show_on_cards=True,
        slug=field.slug,
    )


def _hidden_pks(event):
    return list(
        SessionField.objects.filter(event=event, show_on_cards=False).values_list(
            "pk", flat=True
        )
    )


def _expected_context(event, *, fields, has_any_fields=False):
    return {
        **panel_context(event, active_nav="settings"),
        "active_tab": "display",
        "tab_urls": settings_tab_urls(event.slug),
        "fields": fields,
        "shown_on_cards_ids": [field.pk for field in fields],
        "has_any_fields": has_any_fields,
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
            context_data=_expected_context(
                event, fields=[_expected_field(field)], has_any_fields=True
            ),
        )

    def test_offers_only_public_fields_that_fit_a_pill(self, panel_client, event):
        public = _create_session_field(event, name="Public", slug="public")
        _create_session_field(event, name="Private", slug="private", is_public=False)
        _create_session_field(event, name="Pitch", slug="pitch", field_type="text")

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/display-settings.html",
            context_data=_expected_context(
                event, fields=[_expected_field(public)], has_any_fields=True
            ),
        )

    def test_flags_events_whose_fields_are_all_private(self, panel_client, event):
        _create_session_field(event, name="Private", slug="private", is_public=False)

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/display-settings.html",
            context_data=_expected_context(event, fields=[], has_any_fields=True),
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

    def test_unticked_field_is_hidden(self, panel_client, event):
        shown = _create_session_field(event, name="Field 1", slug="field-1")
        hidden = _create_session_field(event, name="Field 2", slug="field-2")

        response = panel_client.post(
            self.get_url(event), data={"show_on_cards": [str(shown.pk)]}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Display settings saved successfully.")],
            url=f"/panel/event/{event.slug}/settings/display/",
        )

        assert _hidden_pks(event) == [hidden.pk]

    # "²" is `str.isdigit()` but not `int()`-parsable, so it must be rejected
    # by the guard rather than crashing the parse below it.
    @pytest.mark.parametrize("raw_id", ("abc", "²"))
    def test_rejects_non_numeric_field_ids(
        self, authenticated_client, active_user, sphere, event, raw_id
    ):
        sphere.managers.add(active_user)
        field = _create_session_field(event, show_on_cards=False)

        response = authenticated_client.post(
            self.get_url(event), data={"show_on_cards": [raw_id]}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Invalid field selection.")],
            url=f"/panel/event/{event.slug}/settings/display/",
        )
        assert _hidden_pks(event) == [field.pk]

    def test_unticking_every_field_hides_them_all(self, event, panel_client):
        field = _create_session_field(event)

        response = panel_client.post(self.get_url(event), data={})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Display settings saved successfully.")],
            url=f"/panel/event/{event.slug}/settings/display/",
        )

        assert _hidden_pks(event) == [field.pk]

    def test_refuses_private_and_foreign_field_ids(self, panel_client, event, sphere):
        shown = _create_session_field(event, slug="shown")
        private = _create_session_field(
            event, slug="private", is_public=False, show_on_cards=False
        )
        other_event = EventFactory(sphere=sphere)
        foreign = _create_session_field(other_event, show_on_cards=False)

        response = panel_client.post(
            self.get_url(event),
            data={"show_on_cards": [str(private.pk), str(foreign.pk)]},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Invalid field selection.")],
            url=f"/panel/event/{event.slug}/settings/display/",
        )
        # Nothing moved: not the ticked field the refused selection left out,
        # not the two it named.
        assert _hidden_pks(event) == [private.pk]
        assert shown.pk not in _hidden_pks(event)
        assert _hidden_pks(other_event) == [foreign.pk]
