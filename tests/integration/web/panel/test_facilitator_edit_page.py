"""Integration tests for the facilitator edit page."""

from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import (
    Facilitator,
    PersonalDataField,
    PersonalDataFieldOption,
    PersonalDataFieldValue,
)
from ludamus.pacts import EventDTO, FacilitatorDTO
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


def _make_facilitator(event, **kwargs):
    defaults = {"display_name": "Alice", "slug": "alice", "user": None}
    defaults.update(kwargs)
    return Facilitator.objects.create(event=event, **defaults)


def _base_context(event):
    return {
        "current_event": EventDTO.model_validate(event),
        "events": [EventDTO.model_validate(event)],
        "is_proposal_active": False,
        "stats": {
            "hosts_count": 0,
            "pending_proposals": 0,
            "rooms_count": 0,
            "scheduled_sessions": 0,
            "total_proposals": 0,
            "total_sessions": 0,
        },
        "active_nav": "facilitators",
    }


class TestFacilitatorEditPageView:
    """Tests for /panel/event/<slug>/facilitators/<facilitator_slug>/edit/ page."""

    @staticmethod
    def get_url(event, facilitator_slug="alice"):
        return reverse(
            "panel:facilitator-edit",
            kwargs={"slug": event.slug, "facilitator_slug": facilitator_slug},
        )

    def test_get_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_get_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_get_redirects_when_event_not_found(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse(
            "panel:facilitator-edit",
            kwargs={"slug": "nonexistent", "facilitator_slug": "alice"},
        )

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url=reverse("panel:index"),
        )

    def test_get_redirects_when_facilitator_not_found(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event, "nonexistent"))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Facilitator not found.")],
            url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
        )

    def test_get_ok_for_sphere_manager(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        facilitator = _make_facilitator(event)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-edit.html",
            context_data={
                **_base_context(event),
                "form": ANY,
                "facilitator": FacilitatorDTO.model_validate(facilitator),
                "personal_fields": [],
            },
        )

    def test_post_redirects_when_event_not_found(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse(
            "panel:facilitator-edit",
            kwargs={"slug": "nonexistent", "facilitator_slug": "alice"},
        )

        response = authenticated_client.post(url, data={"display_name": "Alice"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url=reverse("panel:index"),
        )

    def test_post_redirects_when_facilitator_not_found(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            self.get_url(event, "nonexistent"), data={"display_name": "Alice"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Facilitator not found.")],
            url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
        )

    def test_post_redirects_and_keeps_cached_display_name(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        facilitator = _make_facilitator(event)

        response = authenticated_client.post(
            self.get_url(event), data={"accreditation_type": "none"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Facilitator updated successfully.")],
            url=reverse(
                "panel:facilitator-detail",
                kwargs={"slug": event.slug, "facilitator_slug": "alice"},
            ),
        )
        facilitator.refresh_from_db()
        # display_name is a read-only cache: a posted value must not change it.
        assert facilitator.display_name == "Alice"

    def test_post_ignores_submitted_display_name(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        facilitator = _make_facilitator(event)

        authenticated_client.post(
            self.get_url(event), data={"display_name": "Hacked Name"}
        )

        facilitator.refresh_from_db()
        assert facilitator.display_name == "Alice"

    def test_post_updates_accreditation_type(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        facilitator = _make_facilitator(event, accreditation_type="none")

        authenticated_client.post(
            self.get_url(event),
            data={"display_name": "Alice", "accreditation_type": "honorary"},
        )

        facilitator.refresh_from_db()
        assert facilitator.accreditation_type == "honorary"

    def test_get_preselects_current_accreditation_type(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        _make_facilitator(event, accreditation_type="guest")

        response = authenticated_client.get(self.get_url(event))

        assert response.context["form"].initial["accreditation_type"] == "guest"

    def test_get_does_not_render_display_name_input(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        facilitator = _make_facilitator(event)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-edit.html",
            context_data={
                **_base_context(event),
                "form": ANY,
                "facilitator": FacilitatorDTO.model_validate(facilitator),
                "personal_fields": [],
            },
            not_contains='name="display_name"',
        )

    def test_post_saves_checkbox_personal_data_field(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        facilitator = _make_facilitator(event)
        field = PersonalDataField.objects.create(
            event=event,
            name="Vegan",
            question="Are you vegan?",
            slug="vegan",
            field_type="checkbox",
            order=0,
        )

        authenticated_client.post(
            self.get_url(event),
            data={"display_name": "Alice", "personal_vegan": "true"},
        )

        hpd = PersonalDataFieldValue.objects.get(facilitator=facilitator, field=field)
        assert hpd.value is True

    def test_post_saves_multiple_personal_data_field(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        facilitator = _make_facilitator(event)
        field = PersonalDataField.objects.create(
            event=event,
            name="Languages",
            question="Which languages?",
            slug="languages",
            field_type="select",
            is_multiple=True,
            order=0,
        )

        authenticated_client.post(
            self.get_url(event),
            data={"display_name": "Alice", "personal_languages": ["en", "pl"]},
        )

        hpd = PersonalDataFieldValue.objects.get(facilitator=facilitator, field=field)
        assert hpd.value == ["en", "pl"]

    def test_post_saves_allow_custom_personal_data_field_from_custom_input(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        facilitator = _make_facilitator(event)
        field = PersonalDataField.objects.create(
            event=event,
            name="System",
            question="Which RPG system?",
            slug="system",
            field_type="text",
            allow_custom=True,
            order=0,
        )

        authenticated_client.post(
            self.get_url(event),
            data={
                "display_name": "Alice",
                "personal_system": "",
                "personal_system_custom": "Homebrew",
            },
        )

        hpd = PersonalDataFieldValue.objects.get(facilitator=facilitator, field=field)
        assert hpd.value == "Homebrew"

    def test_get_renders_all_personal_field_types(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        facilitator = _make_facilitator(event)

        languages = PersonalDataField.objects.create(
            event=event,
            name="Languages",
            question="Which languages?",
            slug="languages",
            field_type="select",
            is_multiple=True,
            help_text="Pick all that apply",
            order=0,
        )
        PersonalDataFieldOption.objects.create(
            field=languages, label="English", value="en", order=0
        )
        PersonalDataFieldOption.objects.create(
            field=languages, label="Polish", value="pl", order=1
        )

        system = PersonalDataField.objects.create(
            event=event,
            name="System",
            question="Which RPG system?",
            slug="system",
            field_type="select",
            allow_custom=True,
            order=1,
        )
        PersonalDataFieldOption.objects.create(
            field=system, label="D&D", value="dnd", order=0
        )

        vegan = PersonalDataField.objects.create(
            event=event,
            name="Vegan",
            question="Are you vegan?",
            slug="vegan",
            field_type="checkbox",
            order=2,
        )

        nickname = PersonalDataField.objects.create(
            event=event,
            name="Nickname",
            question="Your nickname",
            slug="nickname",
            field_type="text",
            allow_custom=True,
            max_length=42,
            help_text="Optional",
            order=3,
        )

        PersonalDataFieldValue.objects.create(
            facilitator=facilitator, event=event, field=languages, value=["en"]
        )
        PersonalDataFieldValue.objects.create(
            facilitator=facilitator, event=event, field=system, value="dnd"
        )
        PersonalDataFieldValue.objects.create(
            facilitator=facilitator, event=event, field=vegan, value=True
        )
        PersonalDataFieldValue.objects.create(
            facilitator=facilitator, event=event, field=nickname, value="Bob"
        )

        response = authenticated_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        html = response.content.decode()
        assert 'name="personal_languages" value="en"\n' in html or (
            'name="personal_languages"' in html and 'value="en"' in html
        )
        assert "Pick all that apply" in html
        assert 'name="personal_system"' in html
        assert 'name="personal_system_custom"' in html
        assert 'name="personal_vegan"' in html
        assert 'name="personal_nickname"' in html
        assert 'maxlength="42"' in html
        assert 'name="personal_nickname_custom"' in html
        assert "Optional" in html
