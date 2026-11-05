"""Facilitator personal data on the proposal edit form."""

from http import HTTPStatus

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.gates.web.django.chronology.panel.views.proposal_edit import (
    PersonalDataCard,
)
from ludamus.links.db.django.models import (
    Facilitator,
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
from tests.integration.conftest import EventFactory
from tests.integration.utils import FormErrorsMatcher, assert_response
from tests.integration.web.panel.helpers import facilitator_list_item_dto
from tests.integration.web.panel.proposal_form.helpers import (
    form_context,
    form_url,
    make_session,
)


class TestEdit:
    def test_get_renders_facilitator_personal_data(self, panel_client, event):
        session = make_session(event)
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )
        session.facilitators.add(facilitator)
        field = PersonalDataField.objects.create(
            event=event,
            name="Nickname",
            question="Your nickname?",
            slug="nick",
            field_type="text",
            order=0,
        )

        response = panel_client.get(form_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={
                **form_context(event, session),
                "all_facilitators": [
                    facilitator_list_item_dto(facilitator, session_count=1)
                ],
                "assigned_facilitator_pks": {facilitator.pk},
                "facilitator_personal_data": [
                    PersonalDataCard(
                        facilitator=FacilitatorDTO.model_validate(facilitator),
                        descriptors=[
                            {
                                "field": OrganizerFieldDTO(
                                    allow_custom=False,
                                    field_type="text",
                                    help_text="",
                                    is_multiple=False,
                                    is_public=False,
                                    max_length=50,
                                    name="Nickname",
                                    options=[],
                                    order=0,
                                    pk=field.pk,
                                    question="Your nickname?",
                                    slug="nick",
                                ),
                                "name_prefix": f"facilitator_{facilitator.pk}_personal",
                                "answer": FieldAnswer(),
                            }
                        ],
                    )
                ],
            },
        )

    def test_post_saves_facilitator_personal_data(self, panel_client, event):
        session = make_session(event)
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )
        session.facilitators.add(facilitator)
        field = PersonalDataField.objects.create(
            event=event,
            name="Vegan",
            question="Are you vegan?",
            slug="vegan",
            field_type="checkbox",
            order=0,
        )

        panel_client.post(
            form_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Test Session",
                "facilitator_name": "Test Host",
                "participants_limit": 5,
                "min_age": 0,
                "personal_data_submitted": "1",
                "personal_data_facilitator_ids": [facilitator.pk],
                f"facilitator_{facilitator.pk}_personal_vegan": "true",
            },
        )

        hpd = PersonalDataFieldValue.objects.get(facilitator=facilitator, field=field)
        assert hpd.value is True

    def test_post_saves_personal_data_of_facilitator_removed_in_same_save(
        self, panel_client, event
    ):
        session = make_session(event)
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )
        session.facilitators.add(facilitator)
        field = PersonalDataField.objects.create(
            event=event,
            name="Allergy",
            question="Any allergy?",
            slug="allergy",
            field_type="text",
            order=0,
        )

        response = panel_client.post(
            form_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Test Session",
                "facilitator_name": "Test Host",
                "participants_limit": 5,
                "min_age": 0,
                "facilitators_submitted": "1",
                "personal_data_submitted": "1",
                "personal_data_facilitator_ids": [facilitator.pk],
                f"facilitator_{facilitator.pk}_personal_allergy": "Peanuts",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal updated successfully.")],
            url=reverse(
                "panel:proposal-detail",
                kwargs={"slug": event.slug, "proposal_id": session.pk},
            ),
        )
        assert not session.facilitators.exists()
        hpd = PersonalDataFieldValue.objects.get(facilitator=facilitator, field=field)
        assert hpd.value == "Peanuts"

    def test_post_saves_multiple_facilitator_personal_data(self, panel_client, event):
        session = make_session(event)
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )
        session.facilitators.add(facilitator)
        field = PersonalDataField.objects.create(
            event=event,
            name="Diet",
            question="Dietary needs?",
            slug="diet",
            field_type="select",
            is_multiple=True,
            order=0,
        )
        for order, value in enumerate(["vegan", "gluten-free"]):
            PersonalDataFieldOption.objects.create(
                field=field, label=value, value=value, order=order
            )

        panel_client.post(
            form_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Test Session",
                "facilitator_name": "Test Host",
                "participants_limit": 5,
                "min_age": 0,
                "personal_data_submitted": "1",
                "personal_data_facilitator_ids": [facilitator.pk],
                f"facilitator_{facilitator.pk}_personal_diet": ["vegan", "gluten-free"],
            },
        )

        hpd = PersonalDataFieldValue.objects.get(facilitator=facilitator, field=field)
        assert hpd.value == ["vegan", "gluten-free"]

    def test_post_saves_allow_custom_facilitator_personal_data(
        self, panel_client, event
    ):
        session = make_session(event)
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )
        session.facilitators.add(facilitator)
        field = PersonalDataField.objects.create(
            event=event,
            name="Allergy",
            question="Any allergy?",
            slug="allergy",
            field_type="text",
            allow_custom=True,
            order=0,
        )

        panel_client.post(
            form_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Test Session",
                "facilitator_name": "Test Host",
                "participants_limit": 5,
                "min_age": 0,
                "personal_data_submitted": "1",
                "personal_data_facilitator_ids": [facilitator.pk],
                f"facilitator_{facilitator.pk}_personal_allergy": "",
                f"facilitator_{facilitator.pk}_personal_allergy_custom": "Peanuts",
            },
        )

        hpd = PersonalDataFieldValue.objects.get(facilitator=facilitator, field=field)
        assert hpd.value == "Peanuts"

    def test_post_keeps_a_write_in_the_form_hands_back(self, panel_client, event):
        session = make_session(event)
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )
        session.facilitators.add(facilitator)
        field = PersonalDataField.objects.create(
            event=event,
            name="Diet",
            question="Any dietary needs?",
            slug="diet",
            field_type="select",
            is_multiple=True,
            allow_custom=True,
            order=0,
        )
        PersonalDataFieldOption.objects.create(
            field=field, label="Vegan", value="vegan", order=0
        )
        PersonalDataFieldValue.objects.create(
            facilitator=facilitator,
            event=event,
            field=field,
            value=["vegan", "no peanuts"],
        )

        panel_client.post(
            form_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Test Session",
                "facilitator_name": "Test Host",
                "participants_limit": 5,
                "min_age": 0,
                "personal_data_submitted": "1",
                "personal_data_facilitator_ids": [facilitator.pk],
                f"facilitator_{facilitator.pk}_personal_diet": ["vegan"],
                f"facilitator_{facilitator.pk}_personal_diet_custom": "no peanuts",
            },
        )

        stored = PersonalDataFieldValue.objects.get(
            facilitator=facilitator, field=field
        )
        assert stored.value == ["vegan", "no peanuts"]

    def test_get_splits_a_stored_write_in_across_control_and_companion(
        self, panel_client, event
    ):
        session = make_session(event)
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )
        session.facilitators.add(facilitator)
        field = PersonalDataField.objects.create(
            event=event,
            name="Diet",
            question="Any dietary needs?",
            slug="diet",
            field_type="select",
            is_multiple=True,
            allow_custom=True,
            order=0,
        )
        option = PersonalDataFieldOption.objects.create(
            field=field, label="Vegan", value="vegan", order=0
        )
        PersonalDataFieldValue.objects.create(
            facilitator=facilitator,
            event=event,
            field=field,
            value=["vegan", "no peanuts"],
        )

        response = panel_client.get(form_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={
                **form_context(event, session),
                "all_facilitators": [
                    facilitator_list_item_dto(facilitator, session_count=1)
                ],
                "assigned_facilitator_pks": {facilitator.pk},
                "facilitator_personal_data": [
                    PersonalDataCard(
                        facilitator=FacilitatorDTO.model_validate(facilitator),
                        descriptors=[
                            {
                                "field": OrganizerFieldDTO(
                                    allow_custom=True,
                                    field_type="select",
                                    help_text="",
                                    is_multiple=True,
                                    is_public=False,
                                    max_length=50,
                                    name="Diet",
                                    options=[
                                        OrganizerFieldOptionDTO(
                                            label="Vegan",
                                            order=0,
                                            pk=option.pk,
                                            value="vegan",
                                        )
                                    ],
                                    order=0,
                                    pk=field.pk,
                                    question="Any dietary needs?",
                                    slug="diet",
                                ),
                                "name_prefix": f"facilitator_{facilitator.pk}_personal",
                                # The stored write-in comes back split: the
                                # option on the control, the rest beside it.
                                "answer": FieldAnswer(
                                    value=["vegan"], custom_value="no peanuts"
                                ),
                            }
                        ],
                    )
                ],
            },
        )

    def test_post_with_only_invalid_personal_data_reports_it_on_the_form(
        self, panel_client, event
    ):
        session = make_session(event)
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )
        session.facilitators.add(facilitator)
        field = PersonalDataField.objects.create(
            event=event,
            name="Allergy",
            question="Any allergy?",
            slug="allergy",
            field_type="text",
            max_length=5,
            order=0,
        )

        response = panel_client.post(
            form_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "New title",
                "facilitator_name": "Test Host",
                "participants_limit": 5,
                "min_age": 0,
                "personal_data_submitted": "1",
                "personal_data_facilitator_ids": [facilitator.pk],
                # Longer than the field allows, so only the personal-data form
                # is invalid — the proposal form itself has nothing to report.
                f"facilitator_{facilitator.pk}_personal_allergy": "Peanuts",
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={
                **form_context(event, session),
                "form": FormErrorsMatcher(
                    __all__=["Fix the facilitator personal data below before saving."]
                ),
                "all_facilitators": [
                    facilitator_list_item_dto(facilitator, session_count=1)
                ],
                "assigned_facilitator_pks": {facilitator.pk},
                "facilitator_personal_data": [
                    PersonalDataCard(
                        facilitator=FacilitatorDTO.model_validate(facilitator),
                        descriptors=[
                            {
                                "field": OrganizerFieldDTO(
                                    allow_custom=False,
                                    field_type="text",
                                    help_text="",
                                    is_multiple=False,
                                    is_public=False,
                                    max_length=5,
                                    name="Allergy",
                                    options=[],
                                    order=0,
                                    pk=field.pk,
                                    question="Any allergy?",
                                    slug="allergy",
                                ),
                                "name_prefix": f"facilitator_{facilitator.pk}_personal",
                                "answer": FieldAnswer(
                                    value="Peanuts",
                                    errors=[
                                        (
                                            "Ensure this value has at most 5 "
                                            "characters (it has 7)."
                                        )
                                    ],
                                ),
                            }
                        ],
                        has_errors=True,
                    )
                ],
            },
        )
        session.refresh_from_db()
        assert session.title == "Test Session"

    def test_invalid_post_preserves_submitted_personal_data(self, panel_client, event):
        session = make_session(event)
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )
        session.facilitators.add(facilitator)
        field = PersonalDataField.objects.create(
            event=event,
            name="Allergy",
            question="Any allergy?",
            slug="allergy",
            field_type="text",
            max_length=50,
            order=0,
        )

        response = panel_client.post(
            form_url(event, session.pk),
            data={
                # Missing title → form invalid, triggers the re-render path.
                "category_id": session.category_id,
                "facilitator_name": "Test Host",
                "participants_limit": 5,
                "min_age": 0,
                "personal_data_submitted": "1",
                "personal_data_facilitator_ids": [facilitator.pk],
                f"facilitator_{facilitator.pk}_personal_allergy": "Peanuts",
            },
        )

        assert response.context["form"].errors
        assert response.context["facilitator_personal_data"] == [
            PersonalDataCard(
                facilitator=FacilitatorDTO.model_validate(facilitator),
                descriptors=[
                    {
                        "field": OrganizerFieldDTO(
                            allow_custom=False,
                            field_type="text",
                            help_text="",
                            is_multiple=False,
                            is_public=False,
                            max_length=50,
                            name="Allergy",
                            options=[],
                            order=0,
                            pk=field.pk,
                            question="Any allergy?",
                            slug="allergy",
                        ),
                        "name_prefix": f"facilitator_{facilitator.pk}_personal",
                        "answer": FieldAnswer(value="Peanuts"),
                    }
                ],
            )
        ]
        assert not PersonalDataFieldValue.objects.exists()

    def test_invalid_post_with_personal_data_marker_and_no_fields(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = make_session(event)
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )
        session.facilitators.add(facilitator)

        response = authenticated_client.post(
            form_url(event, session.pk),
            data={
                # Missing title → form invalid, triggers the re-render path.
                "category_id": session.category_id,
                "facilitator_name": "Test Host",
                "participants_limit": 5,
                "min_age": 0,
                "personal_data_submitted": "1",
                "personal_data_facilitator_ids": [facilitator.pk],
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={
                **form_context(event, session),
                "all_facilitators": [
                    facilitator_list_item_dto(facilitator, session_count=1)
                ],
                "assigned_facilitator_pks": {facilitator.pk},
            },
        )

    @pytest.mark.parametrize("from_other_event", (True, False))
    @pytest.mark.parametrize("answer", ("Peanuts", "Far too long an answer"))
    def test_post_ignores_personal_data_for_facilitator_not_on_proposal(
        self, panel_client, sphere, event, from_other_event, answer
    ):
        session = make_session(event)
        unassigned = Facilitator.objects.create(
            event=EventFactory(sphere=sphere) if from_other_event else event,
            display_name="Bob",
            slug="bob",
            user=None,
        )
        PersonalDataField.objects.create(
            event=event,
            name="Allergy",
            question="Any allergy?",
            slug="allergy",
            field_type="text",
            max_length=10,
            order=0,
        )

        response = panel_client.post(
            form_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Renamed",
                "facilitator_name": "Test Host",
                "participants_limit": 5,
                "min_age": 0,
                "personal_data_submitted": "1",
                "personal_data_facilitator_ids": [unassigned.pk],
                f"facilitator_{unassigned.pk}_personal_allergy": answer,
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal updated successfully.")],
            url=reverse(
                "panel:proposal-detail",
                kwargs={"slug": event.slug, "proposal_id": session.pk},
            ),
        )
        session.refresh_from_db()
        assert session.title == "Renamed"
        assert not PersonalDataFieldValue.objects.exists()
