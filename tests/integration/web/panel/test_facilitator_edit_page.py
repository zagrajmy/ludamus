"""Integration tests for the facilitator edit page."""

from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import (
    FacilitatorChangeLog,
    PersonalDataField,
    PersonalDataFieldOption,
    PersonalDataFieldValue,
)
from ludamus.pacts import (
    FacilitatorDTO,
    FieldAnswer,
    OrganizerFieldDTO,
    OrganizerFieldOptionDTO,
)
from tests.integration.conftest import UserFactory
from tests.integration.utils import (
    FormErrorsMatcher,
    assert_login_required,
    assert_response,
)
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_facilitator_not_found,
    assert_not_a_manager,
    make_facilitator,
    panel_context,
)


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

        assert_login_required(response, url)

    def test_get_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event))

        assert_not_a_manager(response)

    def test_get_redirects_when_event_not_found(self, panel_client):
        url = reverse(
            "panel:facilitator-edit",
            kwargs={"slug": "nonexistent", "facilitator_slug": "alice"},
        )

        response = panel_client.get(url)

        assert_event_not_found(response)

    def test_get_redirects_when_facilitator_not_found(self, panel_client, event):
        response = panel_client.get(self.get_url(event, "nonexistent"))

        assert_facilitator_not_found(response, event)

    def test_get_ok_for_sphere_manager(self, panel_client, event):
        facilitator = make_facilitator(event)

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-edit.html",
            context_data={
                **panel_context(event, active_nav="facilitators"),
                "form": ANY,
                "facilitator": FacilitatorDTO.model_validate(facilitator),
                "field_descriptors": [],
            },
        )

    def test_get_shows_the_organizer_read_only(self, panel_client, event):
        organizer = UserFactory(name="Olga Organizer", email="olga@example.com")
        facilitator = make_facilitator(event, organizer=organizer)

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-edit.html",
            context_data={
                **panel_context(event, active_nav="facilitators"),
                "form": ANY,
                "facilitator": (
                    FacilitatorDTO.model_validate(facilitator).model_copy(
                        update={"organizer_name": "Olga Organizer"}
                    )
                ),
                "field_descriptors": [],
            },
        )

    def test_post_redirects_when_event_not_found(self, panel_client):
        url = reverse(
            "panel:facilitator-edit",
            kwargs={"slug": "nonexistent", "facilitator_slug": "alice"},
        )

        response = panel_client.post(url, data={"display_name": "Alice"})

        assert_event_not_found(response)

    def test_post_redirects_when_facilitator_not_found(self, panel_client, event):
        response = panel_client.post(
            self.get_url(event, "nonexistent"), data={"display_name": "Alice"}
        )

        assert_facilitator_not_found(response, event)

    def test_post_invalid_accreditation_rerenders_form_with_error(
        self, panel_client, event
    ):
        facilitator = make_facilitator(event)

        response = panel_client.post(
            self.get_url(event), data={"accreditation_type": "bogus"}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-edit.html",
            context_data={
                **panel_context(event, active_nav="facilitators"),
                "form": FormErrorsMatcher(
                    accreditation_type=[
                        (
                            "Select a valid choice. bogus is not one of the"
                            " available choices."
                        )
                    ]
                ),
                "facilitator": FacilitatorDTO.model_validate(facilitator),
                "field_descriptors": [],
            },
        )

    def test_post_redirects_and_keeps_cached_display_name(self, panel_client, event):
        facilitator = make_facilitator(event)

        response = panel_client.post(
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

    def test_post_ignores_submitted_display_name(self, panel_client, event):
        facilitator = make_facilitator(event)

        panel_client.post(self.get_url(event), data={"display_name": "Hacked Name"})

        facilitator.refresh_from_db()
        assert facilitator.display_name == "Alice"

    def test_post_updates_accreditation_type(self, panel_client, event):
        facilitator = make_facilitator(event, accreditation_type="none")

        panel_client.post(
            self.get_url(event),
            data={"display_name": "Alice", "accreditation_type": "honorary"},
        )

        facilitator.refresh_from_db()
        assert facilitator.accreditation_type == "honorary"

    def test_post_saves_internal_comment(self, panel_client, active_user, event):
        facilitator = make_facilitator(event)

        panel_client.post(
            self.get_url(event),
            data={
                "accreditation_type": "none",
                "internal_comment": "Possible duplicate of Bob",
            },
        )

        facilitator.refresh_from_db()
        assert facilitator.internal_comment == "Possible duplicate of Bob"
        log = FacilitatorChangeLog.objects.get(facilitator=facilitator)
        assert log.user_id == active_user.pk
        assert log.changes == [
            {
                "field": "internal_comment",
                "field_id": None,
                "old": "",
                "new": "Possible duplicate of Bob",
            }
        ]

    def test_post_marks_facilitator_as_multi_session(
        self, panel_client, active_user, event
    ):
        facilitator = make_facilitator(event)

        panel_client.post(
            self.get_url(event),
            data={"accreditation_type": "none", "multi_session": "on"},
        )

        facilitator.refresh_from_db()
        assert facilitator.multi_session
        log = FacilitatorChangeLog.objects.get(facilitator=facilitator)
        assert log.user_id == active_user.pk
        assert log.changes == [
            {"field": "multi_session", "field_id": None, "old": False, "new": True}
        ]

    def test_get_preselects_current_accreditation_type(self, panel_client, event):
        make_facilitator(event, accreditation_type="guest")

        response = panel_client.get(self.get_url(event))

        assert response.context["form"].initial["accreditation_type"] == "guest"

    def test_get_does_not_render_display_name_input(self, panel_client, event):
        facilitator = make_facilitator(event)

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-edit.html",
            context_data={
                **panel_context(event, active_nav="facilitators"),
                "form": ANY,
                "facilitator": FacilitatorDTO.model_validate(facilitator),
                "field_descriptors": [],
            },
            not_contains='name="display_name"',
        )

    def test_post_saves_checkbox_personal_data_field(self, panel_client, event):
        facilitator = make_facilitator(event)
        field = PersonalDataField.objects.create(
            event=event,
            name="Vegan",
            question="Are you vegan?",
            slug="vegan",
            field_type="checkbox",
            order=0,
        )

        panel_client.post(
            self.get_url(event),
            data={"display_name": "Alice", "personal_vegan": "true"},
        )

        hpd = PersonalDataFieldValue.objects.get(facilitator=facilitator, field=field)
        assert hpd.value is True

    def test_post_saves_multiple_personal_data_field(self, panel_client, event):
        facilitator = make_facilitator(event)
        field = PersonalDataField.objects.create(
            event=event,
            name="Languages",
            question="Which languages?",
            slug="languages",
            field_type="select",
            is_multiple=True,
            order=0,
        )
        for order, value in enumerate(["en", "pl"]):
            PersonalDataFieldOption.objects.create(
                field=field, label=value.upper(), value=value, order=order
            )

        panel_client.post(
            self.get_url(event),
            data={"display_name": "Alice", "personal_languages": ["en", "pl"]},
        )

        hpd = PersonalDataFieldValue.objects.get(facilitator=facilitator, field=field)
        assert hpd.value == ["en", "pl"]

    def test_post_saves_allow_custom_personal_data_field_from_custom_input(
        self, panel_client, event
    ):
        facilitator = make_facilitator(event)
        field = PersonalDataField.objects.create(
            event=event,
            name="System",
            question="Which RPG system?",
            slug="system",
            field_type="text",
            allow_custom=True,
            order=0,
        )

        panel_client.post(
            self.get_url(event),
            data={
                "display_name": "Alice",
                "personal_system": "",
                "personal_system_custom": "Homebrew",
            },
        )

        hpd = PersonalDataFieldValue.objects.get(facilitator=facilitator, field=field)
        assert hpd.value == "Homebrew"

    def test_post_keeps_comma_inside_a_multi_value_write_in(self, panel_client, event):
        facilitator = make_facilitator(event)
        field = PersonalDataField.objects.create(
            event=event,
            name="Languages",
            question="Which languages?",
            slug="languages",
            field_type="select",
            is_multiple=True,
            allow_custom=True,
            order=0,
        )
        PersonalDataFieldOption.objects.create(
            field=field, label="English", value="en", order=0
        )

        response = panel_client.post(
            self.get_url(event),
            data={
                "display_name": "Alice",
                "personal_languages": ["en"],
                "personal_languages_custom": "śląski, ale tylko trochę",
            },
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
        hpd = PersonalDataFieldValue.objects.get(facilitator=facilitator, field=field)
        assert hpd.value == ["en", "śląski, ale tylko trochę"]

    def test_get_splits_a_stored_write_in_across_control_and_companion(
        self, panel_client, event
    ):
        facilitator = make_facilitator(event)
        field = PersonalDataField.objects.create(
            event=event,
            name="Languages",
            question="Which languages?",
            slug="languages",
            field_type="select",
            is_multiple=True,
            allow_custom=True,
            order=0,
        )
        option = PersonalDataFieldOption.objects.create(
            field=field, label="English", value="en", order=0
        )
        PersonalDataFieldValue.objects.create(
            facilitator=facilitator, event=event, field=field, value=["en", "śląski"]
        )

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-edit.html",
            context_data={
                **panel_context(event, active_nav="facilitators"),
                "form": ANY,
                "facilitator": FacilitatorDTO.model_validate(facilitator),
                "field_descriptors": [
                    {
                        "field": OrganizerFieldDTO(
                            allow_custom=True,
                            field_type="select",
                            help_text="",
                            is_multiple=True,
                            is_public=False,
                            max_length=50,
                            name="Languages",
                            options=[
                                OrganizerFieldOptionDTO(
                                    label="English", order=0, pk=option.pk, value="en"
                                )
                            ],
                            order=0,
                            pk=field.pk,
                            question="Which languages?",
                            slug="languages",
                        ),
                        "name_prefix": "personal",
                        # The stored write-in comes back split: the option on
                        # the control, the rest beside it.
                        "answer": FieldAnswer(value=["en"], custom_value="śląski"),
                    }
                ],
            },
        )

    def test_get_renders_all_personal_field_types(self, panel_client, event):
        facilitator = make_facilitator(event)

        languages = PersonalDataField.objects.create(
            event=event,
            name="Languages",
            question="Which languages?",
            slug="languages",
            field_type="select",
            is_multiple=True,
            allow_custom=True,
            help_text="Pick all that apply",
            order=0,
        )
        english = PersonalDataFieldOption.objects.create(
            field=languages, label="English", value="en", order=0
        )
        polish = PersonalDataFieldOption.objects.create(
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
        dnd = PersonalDataFieldOption.objects.create(
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
            facilitator=facilitator,
            event=event,
            field=languages,
            value=["en", "śląski, ale tylko trochę"],
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

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-edit.html",
            context_data={
                **panel_context(event, active_nav="facilitators"),
                "form": ANY,
                "facilitator": FacilitatorDTO.model_validate(facilitator),
                "field_descriptors": [
                    {
                        "field": OrganizerFieldDTO(
                            allow_custom=True,
                            field_type="select",
                            help_text="Pick all that apply",
                            is_multiple=True,
                            is_public=False,
                            max_length=50,
                            name="Languages",
                            options=[
                                OrganizerFieldOptionDTO(
                                    label="English", order=0, pk=english.pk, value="en"
                                ),
                                OrganizerFieldOptionDTO(
                                    label="Polish", order=1, pk=polish.pk, value="pl"
                                ),
                            ],
                            order=0,
                            pk=languages.pk,
                            question="Which languages?",
                            slug="languages",
                        ),
                        "name_prefix": "personal",
                        "answer": FieldAnswer(
                            value=["en"], custom_value="śląski, ale tylko trochę"
                        ),
                    },
                    {
                        "field": OrganizerFieldDTO(
                            allow_custom=True,
                            field_type="select",
                            help_text="",
                            is_multiple=False,
                            is_public=False,
                            max_length=50,
                            name="System",
                            options=[
                                OrganizerFieldOptionDTO(
                                    label="D&D", order=0, pk=dnd.pk, value="dnd"
                                )
                            ],
                            order=1,
                            pk=system.pk,
                            question="Which RPG system?",
                            slug="system",
                        ),
                        "name_prefix": "personal",
                        "answer": FieldAnswer(value="dnd", custom_value=""),
                    },
                    {
                        "field": OrganizerFieldDTO(
                            allow_custom=False,
                            field_type="checkbox",
                            help_text="",
                            is_multiple=False,
                            is_public=False,
                            max_length=50,
                            name="Vegan",
                            options=[],
                            order=2,
                            pk=vegan.pk,
                            question="Are you vegan?",
                            slug="vegan",
                        ),
                        "name_prefix": "personal",
                        "answer": FieldAnswer(value=True, custom_value=""),
                    },
                    {
                        "field": OrganizerFieldDTO(
                            allow_custom=True,
                            field_type="text",
                            help_text="Optional",
                            is_multiple=False,
                            is_public=False,
                            max_length=42,
                            name="Nickname",
                            options=[],
                            order=3,
                            pk=nickname.pk,
                            question="Your nickname",
                            slug="nickname",
                        ),
                        "name_prefix": "personal",
                        "answer": FieldAnswer(value="Bob", custom_value=""),
                    },
                ],
            },
        )
