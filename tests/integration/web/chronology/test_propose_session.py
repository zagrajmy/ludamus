from datetime import timedelta
from http import HTTPStatus
from unittest.mock import patch

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import (
    EventProposalSettings,
    Facilitator,
    HostPersonalData,
    PersonalDataField,
    PersonalDataFieldOption,
    PersonalDataFieldRequirement,
    Session,
    SessionField,
    SessionFieldOption,
    SessionFieldRequirement,
    SessionFieldValue,
    TimeSlotRequirement,
    Track,
)
from ludamus.pacts import EventDTO, EventProposalSettingsDTO, ProposalCategoryDTO
from tests.integration.conftest import ProposalCategoryFactory, TimeSlotFactory
from tests.integration.utils import assert_response


class TestProposeSessionPageView:
    URL_NAME = "web:chronology:session-propose"

    def _get_url(self, event_slug: str) -> str:
        return reverse(self.URL_NAME, kwargs={"event_slug": event_slug})

    def _get_category_url(self, event_slug: str) -> str:
        return reverse(
            "web:chronology:session-propose-category", kwargs={"event_slug": event_slug}
        )

    def _get_personal_url(self, event_slug: str) -> str:
        return reverse(
            "web:chronology:session-propose-personal", kwargs={"event_slug": event_slug}
        )

    def _get_timeslots_url(self, event_slug: str) -> str:
        return reverse(
            "web:chronology:session-propose-timeslots",
            kwargs={"event_slug": event_slug},
        )

    def _get_details_url(self, event_slug: str) -> str:
        return reverse(
            "web:chronology:session-propose-details", kwargs={"event_slug": event_slug}
        )

    def _get_review_url(self, event_slug: str) -> str:
        return reverse(
            "web:chronology:session-propose-review", kwargs={"event_slug": event_slug}
        )

    def _get_submit_url(self, event_slug: str) -> str:
        return reverse(
            "web:chronology:session-propose-submit", kwargs={"event_slug": event_slug}
        )

    def _activate_proposals(self, event, faker, time_zone):
        event.proposal_start_time = faker.date_time_between(
            "-10d", "-1d", tzinfo=time_zone
        )
        event.proposal_end_time = faker.date_time_between(
            "+1d", "+10d", tzinfo=time_zone
        )
        event.save()

    def _set_wizard_category(self, client, event, category):
        session = client.session
        session[f"propose_{event.slug}"] = {"category_id": category.pk}
        session.save()

    def _set_wizard_full(self, client, event, category, **extra):
        session = client.session
        wizard = {
            "category_id": category.pk,
            "contact_email": "proposer@example.com",
            "session_data": {
                "display_name": "Test User",
                "title": "Test Session",
                "participants_limit": 6,
            },
            **extra,
        }
        session[f"propose_{event.slug}"] = wizard
        session.save()

    # -- GET tests --

    def test_get_requires_login(self, client, event, faker, time_zone):
        self._activate_proposals(event, faker, time_zone)
        response = client.get(self._get_url(event.slug))

        assert response.status_code == HTTPStatus.FOUND

    def test_get_redirects_when_proposals_inactive(self, authenticated_client, event):
        response = authenticated_client.get(self._get_url(event.slug))

        assert response.status_code == HTTPStatus.FOUND

    def test_get_shows_category_selection(
        self, authenticated_client, event, faker, time_zone
    ):
        self._activate_proposals(event, faker, time_zone)
        cat1 = ProposalCategoryFactory(event=event, name="Board Game")
        cat2 = ProposalCategoryFactory(event=event, name="RPG Session")

        response = authenticated_client.get(self._get_url(event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "event": EventDTO.model_validate(event),
                "proposal_settings": EventProposalSettingsDTO.model_validate(
                    EventProposalSettings.objects.get(event=event)
                ),
                "categories": [
                    ProposalCategoryDTO.model_validate(cat1),
                    ProposalCategoryDTO.model_validate(cat2),
                ],
                "step": "category",
                "current_step": "category",
                "wizard_steps": [
                    {"key": "category"},
                    {"key": "personal"},
                    {"key": "timeslots"},
                    {"key": "details"},
                    {"key": "review"},
                ],
                "show_login_nudge": False,
                "login_url": f"/crowd/login-required/?next={self._get_url(event.slug)}",
                "wizard_part_template": "chronology/propose/parts/category.html",
            },
            template_name="chronology/propose/base.html",
        )

    def test_get_skips_single_category(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)

        response = authenticated_client.get(self._get_url(event.slug))
        form = response.context["form"]

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "event": EventDTO.model_validate(event),
                "category": ProposalCategoryDTO.model_validate(proposal_category),
                "proposal_settings": EventProposalSettingsDTO.model_validate(
                    EventProposalSettings.objects.get(event=event)
                ),
                "form": form,
                "field_descriptors": [],
                "current_step": "personal",
                "wizard_steps": [
                    {"key": "personal"},
                    {"key": "details"},
                    {"key": "review"},
                ],
                "show_back_button": False,
                "show_login_nudge": False,
                "login_url": f"/crowd/login-required/?next={self._get_url(event.slug)}",
                "wizard_part_template": "chronology/propose/parts/personal.html",
            },
            template_name="chronology/propose/base.html",
        )
        assert form["contact_email"] is not None

    def test_get_stores_category_in_session_on_auto_advance(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)

        authenticated_client.get(self._get_url(event.slug))

        wizard = authenticated_client.session[f"propose_{event.slug}"]
        assert wizard["category_id"] == proposal_category.pk

    # -- Category POST tests --

    def test_post_category_stores_in_session(
        self, authenticated_client, event, faker, time_zone
    ):
        self._activate_proposals(event, faker, time_zone)
        cat = ProposalCategoryFactory(event=event, name="RPG Session")
        ProposalCategoryFactory(event=event, name="Workshop")

        response = authenticated_client.post(
            self._get_category_url(event.slug), {"category_id": cat.pk}
        )

        assert response.status_code == HTTPStatus.OK
        wizard = authenticated_client.session[f"propose_{event.slug}"]
        assert wizard["category_id"] == cat.pk

    def test_post_different_category_clears_wizard_data(
        self, authenticated_client, event, faker, time_zone
    ):
        self._activate_proposals(event, faker, time_zone)
        cat_a = ProposalCategoryFactory(event=event, name="RPG")
        cat_b = ProposalCategoryFactory(event=event, name="Workshop")
        self._set_wizard_full(authenticated_client, event, cat_a)

        authenticated_client.post(
            self._get_category_url(event.slug), {"category_id": cat_b.pk}
        )

        wizard = authenticated_client.session[f"propose_{event.slug}"]
        assert wizard["category_id"] == cat_b.pk
        assert "session_data" not in wizard
        assert "contact_email" not in wizard

    def test_post_same_category_preserves_wizard_data(
        self, authenticated_client, event, faker, time_zone
    ):
        self._activate_proposals(event, faker, time_zone)
        cat = ProposalCategoryFactory(event=event, name="RPG")
        ProposalCategoryFactory(event=event, name="Workshop")
        self._set_wizard_full(authenticated_client, event, cat)

        authenticated_client.post(
            self._get_category_url(event.slug), {"category_id": cat.pk}
        )

        wizard = authenticated_client.session[f"propose_{event.slug}"]
        assert wizard["category_id"] == cat.pk
        assert wizard["session_data"]["title"] == "Test Session"

    def test_post_category_without_choice_shows_error(
        self, authenticated_client, event, faker, time_zone
    ):
        self._activate_proposals(event, faker, time_zone)
        ProposalCategoryFactory(event=event)
        ProposalCategoryFactory(event=event)

        response = authenticated_client.post(self._get_category_url(event.slug), {})

        assert response.status_code == HTTPStatus.OK
        assert response.context["error"]

    def test_post_category_advances_to_personal_step(
        self, authenticated_client, event, faker, time_zone
    ):
        self._activate_proposals(event, faker, time_zone)
        cat = ProposalCategoryFactory(event=event, name="RPG")
        ProposalCategoryFactory(event=event, name="Workshop")
        field = PersonalDataField.objects.create(
            event=event, name="Phone", question="What is your phone?", slug="phone"
        )
        PersonalDataFieldRequirement.objects.create(
            category=cat, field=field, is_required=True
        )

        response = authenticated_client.post(
            self._get_category_url(event.slug), {"category_id": cat.pk}
        )

        assert response.status_code == HTTPStatus.OK
        assert response.context["form"] is not None
        assert len(response.context["field_descriptors"]) == 1
        assert response.context["field_descriptors"][0]["name"] == "What is your phone?"

    def test_post_category_shows_personal_step_even_without_fields(
        self, authenticated_client, event, faker, time_zone
    ):
        self._activate_proposals(event, faker, time_zone)
        cat = ProposalCategoryFactory(event=event, name="RPG")
        ProposalCategoryFactory(event=event, name="Workshop")

        response = authenticated_client.post(
            self._get_category_url(event.slug), {"category_id": cat.pk}
        )

        # Always shows personal step for contact email, even without extra fields
        assert response.status_code == HTTPStatus.OK
        assert response.template_name == "chronology/propose/parts/personal.html"
        assert response.context["form"]["contact_email"] is not None

    # -- Personal data POST tests --

    def test_post_personal_data_valid(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        field = PersonalDataField.objects.create(
            event=event, name="Phone", question="What is your phone?", slug="phone"
        )
        PersonalDataFieldRequirement.objects.create(
            category=proposal_category, field=field, is_required=True
        )
        self._set_wizard_category(authenticated_client, event, proposal_category)

        response = authenticated_client.post(
            self._get_personal_url(event.slug),
            {"personal_phone": "+48 123", "contact_email": "test@example.com"},
        )

        assert response.status_code == HTTPStatus.OK
        wizard = authenticated_client.session[f"propose_{event.slug}"]
        assert wizard["personal_data"]["personal_phone"] == "+48 123"
        assert wizard["contact_email"] == "test@example.com"

    def test_post_personal_data_invalid_shows_errors(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        field = PersonalDataField.objects.create(
            event=event, name="Phone", question="What is your phone?", slug="phone"
        )
        PersonalDataFieldRequirement.objects.create(
            category=proposal_category, field=field, is_required=True
        )
        self._set_wizard_category(authenticated_client, event, proposal_category)

        response = authenticated_client.post(
            self._get_personal_url(event.slug), {}  # missing required phone
        )

        assert response.status_code == HTTPStatus.OK
        assert response.context["form"].errors

    def test_post_personal_data_select_field(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        field = PersonalDataField.objects.create(
            event=event,
            name="T-Shirt",
            question="What is your T-Shirt size?",
            slug="tshirt",
            field_type="select",
        )
        PersonalDataFieldOption.objects.create(
            field=field, label="Small", value="S", order=0
        )
        PersonalDataFieldOption.objects.create(
            field=field, label="Medium", value="M", order=1
        )
        PersonalDataFieldRequirement.objects.create(
            category=proposal_category, field=field, is_required=False
        )
        self._set_wizard_category(authenticated_client, event, proposal_category)

        response = authenticated_client.post(
            self._get_personal_url(event.slug),
            {"personal_tshirt": "M", "contact_email": "test@example.com"},
        )

        assert response.status_code == HTTPStatus.OK
        wizard = authenticated_client.session[f"propose_{event.slug}"]
        assert wizard["personal_data"]["personal_tshirt"] == "M"
        assert wizard["contact_email"] == "test@example.com"

    # -- Time slot POST tests --

    def test_personal_step_prefills_from_saved_data(
        self,
        authenticated_client,
        event,
        faker,
        time_zone,
        proposal_category,
        active_user,
    ):
        self._activate_proposals(event, faker, time_zone)
        field = PersonalDataField.objects.create(
            event=event, name="Phone", question="What is your phone?", slug="phone"
        )
        PersonalDataFieldRequirement.objects.create(
            category=proposal_category, field=field, is_required=True
        )
        # Simulate previously saved personal data via an existing Facilitator
        facilitator = Facilitator.objects.create(
            event=event, user=active_user, display_name=active_user.name, slug="active"
        )
        HostPersonalData.objects.create(
            facilitator=facilitator, event=event, field=field, value="+48 999"
        )
        self._set_wizard_category(authenticated_client, event, proposal_category)

        response = authenticated_client.post(
            self._get_category_url(event.slug), {"category_id": proposal_category.pk}
        )

        assert response.status_code == HTTPStatus.OK
        form = response.context["form"]
        assert form.initial["personal_phone"] == "+48 999"

    def test_post_personal_advances_to_timeslots(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        field = PersonalDataField.objects.create(
            event=event, name="Phone", question="What is your phone?", slug="phone"
        )
        PersonalDataFieldRequirement.objects.create(
            category=proposal_category, field=field, is_required=True
        )
        slot1 = TimeSlotFactory(event=event)
        slot2 = TimeSlotFactory(
            event=event,
            start_time=event.start_time + timedelta(hours=3),
            end_time=event.start_time + timedelta(hours=5),
        )
        TimeSlotRequirement.objects.create(category=proposal_category, time_slot=slot1)
        TimeSlotRequirement.objects.create(category=proposal_category, time_slot=slot2)
        self._set_wizard_category(authenticated_client, event, proposal_category)

        response = authenticated_client.post(
            self._get_personal_url(event.slug),
            {"personal_phone": "+48 123", "contact_email": "test@example.com"},
        )

        assert response.status_code == HTTPStatus.OK
        assert [
            slot["id"] for slot in response.context["slot_descriptors"][0]["slots"]
        ] == [slot1.pk, slot2.pk]

    def test_post_personal_skips_single_timeslot(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        field = PersonalDataField.objects.create(
            event=event, name="Phone", question="What is your phone?", slug="phone"
        )
        PersonalDataFieldRequirement.objects.create(
            category=proposal_category, field=field, is_required=True
        )
        slot = TimeSlotFactory(event=event)
        TimeSlotRequirement.objects.create(category=proposal_category, time_slot=slot)
        self._set_wizard_category(authenticated_client, event, proposal_category)

        response = authenticated_client.post(
            self._get_personal_url(event.slug),
            {"personal_phone": "+48 123", "contact_email": "test@example.com"},
        )

        assert response.status_code == HTTPStatus.OK
        assert response.template_name == "chronology/propose/parts/details.html"
        assert [s["key"] for s in response.context["wizard_steps"]] == [
            "personal",
            "details",
            "review",
        ]
        wizard = authenticated_client.session[f"propose_{event.slug}"]
        assert wizard["time_slot_ids"] == [slot.pk]

    def test_single_category_single_timeslot_defaults_are_submitted(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        slot = TimeSlotFactory(event=event)
        TimeSlotRequirement.objects.create(category=proposal_category, time_slot=slot)

        response = authenticated_client.get(self._get_url(event.slug))
        assert response.status_code == HTTPStatus.OK
        wizard = authenticated_client.session[f"propose_{event.slug}"]
        assert wizard["category_id"] == proposal_category.pk

        response = authenticated_client.post(
            self._get_personal_url(event.slug), {"contact_email": "test@example.com"}
        )
        assert response.status_code == HTTPStatus.OK
        assert response.template_name == "chronology/propose/parts/details.html"
        wizard = authenticated_client.session[f"propose_{event.slug}"]
        assert wizard["category_id"] == proposal_category.pk
        assert wizard["time_slot_ids"] == [slot.pk]

        response = authenticated_client.post(
            self._get_details_url(event.slug),
            {
                "display_name": "Presenter",
                "title": "Skipped Defaults",
                "description": "Single category and slot",
                "participants_limit": proposal_category.min_participants_limit,
            },
        )
        assert response.status_code == HTTPStatus.OK
        assert response.template_name == "chronology/propose/parts/review.html"
        assert response.context["review"]["category_name"] == proposal_category.name
        assert response.context["review"]["time_slots"][0]["slots"][0]["id"] == slot.pk

        response = authenticated_client.post(self._get_submit_url(event.slug))

        assert response.status_code == HTTPStatus.FOUND
        session = Session.objects.get(title="Skipped Defaults")
        assert session.category_id == proposal_category.pk
        assert list(session.time_slots.values_list("pk", flat=True)) == [slot.pk]

    def test_post_timeslots_stores_in_session(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        slot1 = TimeSlotFactory(event=event)
        slot2 = TimeSlotFactory(
            event=event,
            start_time=event.start_time + timedelta(hours=3),
            end_time=event.start_time + timedelta(hours=5),
        )
        TimeSlotRequirement.objects.create(category=proposal_category, time_slot=slot1)
        TimeSlotRequirement.objects.create(category=proposal_category, time_slot=slot2)
        self._set_wizard_category(authenticated_client, event, proposal_category)

        response = authenticated_client.post(
            self._get_timeslots_url(event.slug),
            {"time_slot_ids": [str(slot1.pk), str(slot2.pk)]},
        )

        assert response.status_code == HTTPStatus.OK
        wizard = authenticated_client.session[f"propose_{event.slug}"]
        assert sorted(wizard["time_slot_ids"]) == sorted([slot1.pk, slot2.pk])
        # Advances to session details
        assert response.context["form"] is not None

    def test_post_timeslots_without_selection_shows_error(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        slot1 = TimeSlotFactory(event=event)
        slot2 = TimeSlotFactory(
            event=event,
            start_time=event.start_time + timedelta(hours=3),
            end_time=event.start_time + timedelta(hours=5),
        )
        TimeSlotRequirement.objects.create(category=proposal_category, time_slot=slot1)
        TimeSlotRequirement.objects.create(category=proposal_category, time_slot=slot2)
        self._set_wizard_category(authenticated_client, event, proposal_category)

        response = authenticated_client.post(self._get_timeslots_url(event.slug), {})

        assert response.status_code == HTTPStatus.OK
        assert response.context["error"]

    def test_post_timeslots_filters_invalid_ids(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        slot1 = TimeSlotFactory(event=event)
        slot2 = TimeSlotFactory(
            event=event,
            start_time=event.start_time + timedelta(hours=3),
            end_time=event.start_time + timedelta(hours=5),
        )
        TimeSlotRequirement.objects.create(category=proposal_category, time_slot=slot1)
        TimeSlotRequirement.objects.create(category=proposal_category, time_slot=slot2)
        self._set_wizard_category(authenticated_client, event, proposal_category)

        response = authenticated_client.post(
            self._get_timeslots_url(event.slug),
            {"time_slot_ids": [str(slot1.pk), "99999"]},
        )

        assert response.status_code == HTTPStatus.OK
        wizard = authenticated_client.session[f"propose_{event.slug}"]
        assert wizard["time_slot_ids"] == [slot1.pk]

    def test_post_timeslots_skips_when_no_requirements(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        self._set_wizard_category(authenticated_client, event, proposal_category)

        response = authenticated_client.post(self._get_timeslots_url(event.slug), {})

        # No time slot requirements — skips to session details
        assert response.status_code == HTTPStatus.OK
        assert response.context["form"] is not None
        assert response.template_name == "chronology/propose/parts/details.html"

    def test_post_timeslots_preserves_selection(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        slot1 = TimeSlotFactory(event=event)
        slot2 = TimeSlotFactory(
            event=event,
            start_time=event.start_time + timedelta(hours=3),
            end_time=event.start_time + timedelta(hours=5),
        )
        TimeSlotRequirement.objects.create(category=proposal_category, time_slot=slot1)
        TimeSlotRequirement.objects.create(category=proposal_category, time_slot=slot2)
        # Pre-set wizard with a selected slot
        session = authenticated_client.session
        session[f"propose_{event.slug}"] = {
            "category_id": proposal_category.pk,
            "time_slot_ids": [slot1.pk],
        }
        session.save()

        # Navigate back to timeslots step
        response = authenticated_client.post(
            self._get_personal_url(event.slug), {"back": "1"}
        )

        # Since no personal fields, it should render timeslots
        assert response.status_code == HTTPStatus.OK

    # -- Session details POST tests --

    def test_post_session_details_valid(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        self._set_wizard_category(authenticated_client, event, proposal_category)

        response = authenticated_client.post(
            self._get_details_url(event.slug),
            {
                "display_name": "Presenter",
                "title": "My RPG Session",
                "description": "A great adventure",
                "participants_limit": "6",
                "min_age": "12",
            },
        )

        assert response.status_code == HTTPStatus.OK
        wizard = authenticated_client.session[f"propose_{event.slug}"]
        assert wizard["session_data"]["title"] == "My RPG Session"
        assert wizard["session_data"]["description"] == "A great adventure"
        assert wizard["session_data"]["participants_limit"] == int("6")
        assert wizard["session_data"]["min_age"] == int("12")

    def test_post_session_details_invalid_shows_errors(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        self._set_wizard_category(authenticated_client, event, proposal_category)

        response = authenticated_client.post(
            self._get_details_url(event.slug),
            {},  # missing required title and participants_limit
        )

        assert response.status_code == HTTPStatus.OK
        assert response.context["form"].errors

    def test_post_session_details_requires_track_when_tracks_exist(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        self._set_wizard_category(authenticated_client, event, proposal_category)
        Track.objects.create(
            event=event, name="Fantasy", slug="fantasy", is_public=True
        )

        response = authenticated_client.post(
            self._get_details_url(event.slug),
            {
                "display_name": "Presenter",
                "title": "My Session",
                "description": "A test session",
                "participants_limit": "4",
            },
        )

        assert response.status_code == HTTPStatus.OK
        assert response.context["track_error"] == "Please select at least one track."

    def test_post_session_details_with_session_fields(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        field = SessionField.objects.create(
            event=event,
            name="RPG System",
            question="What RPG system will you use?",
            slug="rpg_system",
        )
        SessionFieldRequirement.objects.create(
            category=proposal_category, field=field, is_required=True
        )
        self._set_wizard_category(authenticated_client, event, proposal_category)

        response = authenticated_client.post(
            self._get_details_url(event.slug),
            {
                "display_name": "Presenter",
                "title": "My Session",
                "description": "A test session",
                "participants_limit": "4",
                "session_rpg_system": "D&D 5e",
            },
        )

        assert response.status_code == HTTPStatus.OK
        wizard = authenticated_client.session[f"propose_{event.slug}"]
        assert wizard["session_data"]["session_rpg_system"] == "D&D 5e"

    def test_post_session_details_with_select_field(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        field = SessionField.objects.create(
            event=event,
            name="Genre",
            question="What genre?",
            slug="genre",
            field_type="select",
        )
        SessionFieldOption.objects.create(
            field=field, label="Fantasy", value="fantasy", order=0
        )
        SessionFieldOption.objects.create(
            field=field, label="Sci-Fi", value="scifi", order=1
        )
        SessionFieldRequirement.objects.create(
            category=proposal_category, field=field, is_required=False
        )
        self._set_wizard_category(authenticated_client, event, proposal_category)

        response = authenticated_client.post(
            self._get_details_url(event.slug),
            {
                "display_name": "Presenter",
                "title": "Space Opera",
                "description": "A test session",
                "participants_limit": "5",
                "session_genre": "scifi",
            },
        )

        assert response.status_code == HTTPStatus.OK
        wizard = authenticated_client.session[f"propose_{event.slug}"]
        assert wizard["session_data"]["session_genre"] == "scifi"

    def test_post_session_renders_form_with_field_descriptors(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        field = SessionField.objects.create(
            event=event,
            name="RPG System",
            question="What RPG system will you use?",
            slug="rpg_system",
        )
        SessionFieldRequirement.objects.create(
            category=proposal_category, field=field, is_required=True
        )
        self._set_wizard_category(authenticated_client, event, proposal_category)

        # Submit invalid to re-render the form with descriptors
        response = authenticated_client.post(
            self._get_details_url(event.slug), {}  # missing required fields
        )

        assert response.status_code == HTTPStatus.OK
        assert len(response.context["field_descriptors"]) == 1
        assert (
            response.context["field_descriptors"][0]["name"]
            == "What RPG system will you use?"
        )

    def test_render_session_step_prefills_from_wizard(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        session = authenticated_client.session
        session[f"propose_{event.slug}"] = {
            "category_id": proposal_category.pk,
            "session_data": {
                "display_name": "Prefilled Name",
                "title": "Prefilled Title",
                "participants_limit": 8,
            },
        }
        session.save()

        # back_to_timeslots with no timeslots skips to session step
        response = authenticated_client.post(
            self._get_timeslots_url(event.slug), {"back": "1"}
        )

        assert response.status_code == HTTPStatus.OK
        assert response.context["form"] is not None

    # -- Back button tests --

    def test_post_back_to_category(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        ProposalCategoryFactory(event=event, name="Workshop")
        self._set_wizard_category(authenticated_client, event, proposal_category)

        response = authenticated_client.post(
            self._get_category_url(event.slug), {"back": "1"}
        )

        assert response.status_code == HTTPStatus.OK
        assert response.context["categories"]

    def test_post_back_to_personal(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        field = PersonalDataField.objects.create(
            event=event, name="Phone", question="What is your phone?", slug="phone"
        )
        PersonalDataFieldRequirement.objects.create(
            category=proposal_category, field=field, is_required=True
        )
        self._set_wizard_category(authenticated_client, event, proposal_category)

        response = authenticated_client.post(
            self._get_personal_url(event.slug), {"back": "1"}
        )

        assert response.status_code == HTTPStatus.OK
        assert response.context["field_descriptors"]

    def test_post_back_to_timeslots(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        slot1 = TimeSlotFactory(event=event)
        slot2 = TimeSlotFactory(
            event=event,
            start_time=event.start_time + timedelta(hours=3),
            end_time=event.start_time + timedelta(hours=5),
        )
        TimeSlotRequirement.objects.create(category=proposal_category, time_slot=slot1)
        TimeSlotRequirement.objects.create(category=proposal_category, time_slot=slot2)
        self._set_wizard_category(authenticated_client, event, proposal_category)

        response = authenticated_client.post(
            self._get_timeslots_url(event.slug), {"back": "1"}
        )

        assert response.status_code == HTTPStatus.OK
        assert response.context["slot_descriptors"]

    def test_post_back_from_details_skips_timeslots_when_none_required(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        field = PersonalDataField.objects.create(
            event=event, name="Phone", question="What is your phone?", slug="phone"
        )
        PersonalDataFieldRequirement.objects.create(
            category=proposal_category, field=field, is_required=True
        )
        self._set_wizard_category(authenticated_client, event, proposal_category)

        response = authenticated_client.post(
            self._get_timeslots_url(event.slug), {"back": "1"}
        )

        assert response.status_code == HTTPStatus.OK
        assert response.template_name == "chronology/propose/parts/personal.html"
        assert response.context["field_descriptors"]

    def test_post_back_from_details_skips_timeslots_when_one_required(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        slot = TimeSlotFactory(event=event)
        TimeSlotRequirement.objects.create(category=proposal_category, time_slot=slot)
        self._set_wizard_category(authenticated_client, event, proposal_category)

        response = authenticated_client.post(
            self._get_timeslots_url(event.slug), {"back": "1"}
        )

        assert response.status_code == HTTPStatus.OK
        assert response.template_name == "chronology/propose/parts/personal.html"

    def test_post_back_to_session(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        self._set_wizard_full(authenticated_client, event, proposal_category)

        response = authenticated_client.post(
            self._get_details_url(event.slug), {"back": "1"}
        )

        assert response.status_code == HTTPStatus.OK
        assert response.context["form"] is not None

    # -- Review step tests --

    def test_post_session_advances_to_review(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        self._set_wizard_category(authenticated_client, event, proposal_category)

        response = authenticated_client.post(
            self._get_details_url(event.slug),
            {
                "display_name": "Presenter",
                "title": "My Session",
                "description": "A test session",
                "participants_limit": "4",
            },
        )

        assert response.status_code == HTTPStatus.OK
        assert response.context["review"]["title"] == "My Session"
        assert response.template_name == "chronology/propose/parts/review.html"

    def test_review_shows_all_wizard_data(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        field = PersonalDataField.objects.create(
            event=event, name="Phone", question="What is your phone?", slug="phone"
        )
        PersonalDataFieldRequirement.objects.create(
            category=proposal_category, field=field, is_required=True
        )
        slot = TimeSlotFactory(event=event)
        TimeSlotRequirement.objects.create(category=proposal_category, time_slot=slot)
        self._set_wizard_full(
            authenticated_client,
            event,
            proposal_category,
            personal_data={"personal_phone": "+48 123"},
            time_slot_ids=[slot.pk],
        )

        # Navigate to review via back_to_session then re-submit
        response = authenticated_client.post(
            self._get_details_url(event.slug),
            {
                "display_name": "Presenter",
                "title": "Full Session",
                "participants_limit": "5",
                "description": "Full description",
                "min_age": "16",
            },
        )

        review = response.context["review"]
        assert review["title"] == "Full Session"
        assert review["min_age"] == int("16")
        assert review["category_name"] == proposal_category.name
        assert len(review["personal_fields"]) == 1
        assert len(review["time_slots"]) == 1

    def test_post_review_renders_review_step(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        self._set_wizard_full(authenticated_client, event, proposal_category)

        response = authenticated_client.post(self._get_review_url(event.slug), {})

        assert response.status_code == HTTPStatus.OK
        assert response.template_name == "chronology/propose/parts/review.html"
        assert response.context["review"]["title"] == "Test Session"

    # -- display_name tests --

    def test_details_prefills_display_name(
        self,
        authenticated_client,
        event,
        faker,
        time_zone,
        proposal_category,
        active_user,
    ):
        self._activate_proposals(event, faker, time_zone)
        self._set_wizard_category(authenticated_client, event, proposal_category)

        response = authenticated_client.post(
            self._get_details_url(event.slug), {"back": "1"}
        )

        form = response.context["form"]
        assert form.initial["display_name"] == active_user.name

    def test_submit_uses_display_name_from_wizard(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        self._set_wizard_full(
            authenticated_client,
            event,
            proposal_category,
            session_data={
                "display_name": "My Custom Name",
                "title": "Test Session",
                "participants_limit": 6,
            },
        )

        authenticated_client.post(self._get_submit_url(event.slug), {})

        session = Session.objects.get(title="Test Session")
        assert session.display_name == "My Custom Name"

    # -- Submit tests --

    def test_submit_creates_session_and_proposal(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        self._set_wizard_full(authenticated_client, event, proposal_category)

        response = authenticated_client.post(self._get_submit_url(event.slug), {})

        assert response.status_code == HTTPStatus.FOUND
        session = Session.objects.get(title="Test Session")
        assert session.participants_limit == int("6")
        assert session.category == proposal_category
        facilitators = list(session.facilitators.all())
        assert len(facilitators) == 1
        assert facilitators[0].user_id == session.presenter_id

    def test_submit_stores_min_age(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        self._set_wizard_full(authenticated_client, event, proposal_category)
        session = authenticated_client.session
        session[f"propose_{event.slug}"]["session_data"]["min_age"] = 12
        session.save()

        authenticated_client.post(self._get_submit_url(event.slug), {})

        session = Session.objects.get(title="Test Session")
        assert session.min_age == int("12")

    def test_submit_without_min_age_defaults_to_zero(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        self._set_wizard_full(authenticated_client, event, proposal_category)

        authenticated_client.post(self._get_submit_url(event.slug), {})

        session = Session.objects.get(title="Test Session")
        assert session.min_age == 0

    def test_submit_saves_personal_data(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        field = PersonalDataField.objects.create(
            event=event, name="Phone", question="What is your phone?", slug="phone"
        )
        PersonalDataFieldRequirement.objects.create(
            category=proposal_category, field=field, is_required=True
        )
        self._set_wizard_full(
            authenticated_client,
            event,
            proposal_category,
            personal_data={"personal_phone": "+48 555"},
        )

        authenticated_client.post(self._get_submit_url(event.slug), {})

        hpd = HostPersonalData.objects.get(event=event, field=field)
        assert hpd.value == "+48 555"

    def test_submit_sets_time_slots(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        slot = TimeSlotFactory(event=event)
        TimeSlotRequirement.objects.create(category=proposal_category, time_slot=slot)
        self._set_wizard_full(
            authenticated_client, event, proposal_category, time_slot_ids=[slot.pk]
        )

        authenticated_client.post(self._get_submit_url(event.slug), {})

        session = Session.objects.get(title="Test Session")
        assert list(session.time_slots.values_list("pk", flat=True)) == [slot.pk]

    def test_submit_saves_session_field_values(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        field = SessionField.objects.create(
            event=event,
            name="RPG System",
            question="What RPG system will you use?",
            slug="rpg_system",
        )
        SessionFieldRequirement.objects.create(
            category=proposal_category, field=field, is_required=True
        )
        self._set_wizard_full(
            authenticated_client,
            event,
            proposal_category,
            session_data={
                "title": "Test Session",
                "participants_limit": 6,
                "session_rpg_system": "D&D 5e",
            },
        )

        authenticated_client.post(self._get_submit_url(event.slug), {})

        session = Session.objects.get(title="Test Session")
        sfv = SessionFieldValue.objects.get(session=session, field=field)
        assert sfv.value == "D&D 5e"

    def test_submit_saves_multiselect_field_as_list(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        field = SessionField.objects.create(
            event=event,
            name="Genres",
            question="What genres?",
            slug="genres",
            field_type="select",
            is_multiple=True,
        )
        SessionFieldOption.objects.create(field=field, value="fantasy", label="Fantasy")
        SessionFieldOption.objects.create(field=field, value="sci-fi", label="Sci-Fi")
        SessionFieldRequirement.objects.create(
            category=proposal_category, field=field, is_required=True
        )
        self._set_wizard_full(
            authenticated_client,
            event,
            proposal_category,
            session_data={
                "title": "Test Session",
                "participants_limit": 6,
                "session_genres": ["fantasy", "sci-fi"],
            },
        )

        authenticated_client.post(self._get_submit_url(event.slug), {})

        session = Session.objects.get(title="Test Session")
        sfv = SessionFieldValue.objects.get(session=session, field=field)
        assert sfv.value == ["fantasy", "sci-fi"]

    def test_submit_saves_checkbox_field_as_boolean(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        field = SessionField.objects.create(
            event=event,
            name="Needs projector",
            question="Do you need a projector?",
            slug="needs_projector",
            field_type="checkbox",
        )
        SessionFieldRequirement.objects.create(
            category=proposal_category, field=field, is_required=False
        )
        self._set_wizard_full(
            authenticated_client,
            event,
            proposal_category,
            session_data={
                "title": "Test Session",
                "participants_limit": 6,
                "session_needs_projector": True,
            },
        )

        authenticated_client.post(self._get_submit_url(event.slug), {})

        session = Session.objects.get(title="Test Session")
        sfv = SessionFieldValue.objects.get(session=session, field=field)
        assert sfv.value is True

    def test_submit_clears_wizard_session(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        self._set_wizard_full(authenticated_client, event, proposal_category)

        authenticated_client.post(self._get_submit_url(event.slug), {})

        assert f"propose_{event.slug}" not in authenticated_client.session

    def test_submit_shows_success_message(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        self._set_wizard_full(authenticated_client, event, proposal_category)

        response = authenticated_client.post(self._get_submit_url(event.slug), {})

        msgs = list(messages.get_messages(response.wsgi_request))
        assert len(msgs) == 1
        assert "Test Session" in str(msgs[0])

    # -- Coverage: error paths and edge cases --

    def test_get_nonexistent_event_redirects(
        self, authenticated_client, event, faker, time_zone
    ):
        self._activate_proposals(event, faker, time_zone)

        response = authenticated_client.get(self._get_url("nonexistent-slug"))

        assert response.status_code == HTTPStatus.FOUND

    def test_post_category_invalid_id_redirects(
        self, authenticated_client, event, faker, time_zone
    ):
        self._activate_proposals(event, faker, time_zone)

        response = authenticated_client.post(
            self._get_category_url(event.slug), {"category_id": 99999}
        )

        assert response.status_code == HTTPStatus.FOUND

    def test_post_personal_without_email_shows_error(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        self._set_wizard_category(authenticated_client, event, proposal_category)

        response = authenticated_client.post(self._get_personal_url(event.slug), {})

        # Contact email is required — stays on personal step
        assert response.status_code == HTTPStatus.OK
        assert response.template_name == "chronology/propose/parts/personal.html"
        assert response.context["form"].errors["contact_email"]

    def test_post_personal_advances_when_no_extra_requirements(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        self._set_wizard_category(authenticated_client, event, proposal_category)

        response = authenticated_client.post(
            self._get_personal_url(event.slug), {"contact_email": "test@example.com"}
        )

        # No personal requirements, but contact email provided — advances
        assert response.status_code == HTTPStatus.OK
        assert response.template_name == "chronology/propose/parts/details.html"

    def test_post_step_without_wizard_category_redirects(
        self, authenticated_client, event, faker, time_zone
    ):
        self._activate_proposals(event, faker, time_zone)

        response = authenticated_client.post(self._get_personal_url(event.slug), {})

        assert response.status_code == HTTPStatus.FOUND

    def test_post_step_with_deleted_category_redirects(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        self._set_wizard_category(authenticated_client, event, proposal_category)
        proposal_category.delete()

        response = authenticated_client.post(self._get_personal_url(event.slug), {})

        assert response.status_code == HTTPStatus.FOUND

    def test_post_personal_field_with_allow_custom(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        field = PersonalDataField.objects.create(
            event=event,
            name="Diet",
            question="What is your diet?",
            slug="diet",
            field_type="select",
            allow_custom=True,
        )
        PersonalDataFieldOption.objects.create(
            field=field, label="Vegan", value="vegan", order=0
        )
        PersonalDataFieldRequirement.objects.create(
            category=proposal_category, field=field, is_required=False
        )
        self._set_wizard_category(authenticated_client, event, proposal_category)

        response = authenticated_client.post(
            self._get_category_url(event.slug), {"category_id": proposal_category.pk}
        )

        assert response.status_code == HTTPStatus.OK
        descriptors = response.context["field_descriptors"]
        assert len(descriptors) == 1
        assert "custom_bound_field" in descriptors[0]

    def test_post_session_field_with_allow_custom(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        field = SessionField.objects.create(
            event=event,
            name="System",
            question="What system will you use?",
            slug="system",
            field_type="select",
            allow_custom=True,
        )
        SessionFieldOption.objects.create(
            field=field, label="D&D", value="dnd", order=0
        )
        SessionFieldRequirement.objects.create(
            category=proposal_category, field=field, is_required=False
        )
        self._set_wizard_category(authenticated_client, event, proposal_category)

        # Submit invalid to re-render form with descriptors
        response = authenticated_client.post(self._get_details_url(event.slug), {})

        assert response.status_code == HTTPStatus.OK
        descriptors = response.context["field_descriptors"]
        assert len(descriptors) == 1
        assert "custom_bound_field" in descriptors[0]

    def test_submit_without_title_redirects(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        session = authenticated_client.session
        session[f"propose_{event.slug}"] = {
            "category_id": proposal_category.pk,
            "session_data": {"participants_limit": 6},
        }
        session.save()

        response = authenticated_client.post(self._get_submit_url(event.slug), {})

        assert response.status_code == HTTPStatus.FOUND

    def test_submit_without_participants_limit_defaults_to_zero(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        session = authenticated_client.session
        session[f"propose_{event.slug}"] = {
            "category_id": proposal_category.pk,
            "session_data": {
                "title": "Test",
                "description": "Desc",
                "display_name": "Presenter",
                "contact_email": "test@example.com",
            },
        }
        session.save()

        response = authenticated_client.post(self._get_submit_url(event.slug), {})

        assert response.status_code == HTTPStatus.FOUND

    def test_submit_with_slug_collision(
        self,
        authenticated_client,
        event,
        faker,
        time_zone,
        proposal_category,
        active_user,
    ):
        self._activate_proposals(event, faker, time_zone)
        # Pre-create a session with the same slug
        Session.objects.create(
            sphere=event.sphere,
            presenter=active_user,
            display_name="Other",
            category=proposal_category,
            title="Test Session",
            slug="test-session",
            status="pending",
            participants_limit=6,
        )
        self._set_wizard_full(authenticated_client, event, proposal_category)

        response = authenticated_client.post(self._get_submit_url(event.slug), {})

        assert response.status_code == HTTPStatus.FOUND
        # A second session was created with a suffixed slug
        assert (
            Session.objects.filter(sphere=event.sphere).count() == 1 + 1
        )  # original + new

    def test_submit_via_htmx_returns_hx_redirect(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        self._set_wizard_full(authenticated_client, event, proposal_category)

        response = authenticated_client.post(
            self._get_submit_url(event.slug), {}, headers={"HX-Request": "true"}
        )

        assert response.status_code == HTTPStatus.OK
        assert "HX-Redirect" in response

    def test_submit_with_custom_session_field_key_skipped(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        self._set_wizard_full(
            authenticated_client,
            event,
            proposal_category,
            session_data={
                "title": "Test Session",
                "participants_limit": 6,
                "session_rpg_custom": "should be skipped",
            },
        )

        authenticated_client.post(self._get_submit_url(event.slug), {})

        session = Session.objects.get(title="Test Session")
        assert SessionFieldValue.objects.filter(session=session).count() == 0

    def test_submit_with_nonexistent_session_field_skipped(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        self._set_wizard_full(
            authenticated_client,
            event,
            proposal_category,
            session_data={
                "title": "Test Session",
                "participants_limit": 6,
                "session_nonexistent": "should be skipped",
            },
        )

        authenticated_client.post(self._get_submit_url(event.slug), {})

        session = Session.objects.get(title="Test Session")
        assert SessionFieldValue.objects.filter(session=session).count() == 0

    def test_submit_with_custom_personal_field_key_skipped(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        self._set_wizard_full(
            authenticated_client,
            event,
            proposal_category,
            personal_data={"personal_diet_custom": "should be skipped"},
        )

        authenticated_client.post(self._get_submit_url(event.slug), {})

        assert HostPersonalData.objects.count() == 0

    def test_submit_with_nonexistent_personal_field_skipped(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        self._set_wizard_full(
            authenticated_client,
            event,
            proposal_category,
            personal_data={"personal_nonexistent": "should be skipped"},
        )

        authenticated_client.post(self._get_submit_url(event.slug), {})

        assert HostPersonalData.objects.count() == 0

    def test_post_personal_multiple_select_field(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        field = PersonalDataField.objects.create(
            event=event,
            name="Allergies",
            question="What are your allergies?",
            slug="allergies",
            field_type="select",
            is_multiple=True,
        )
        PersonalDataFieldOption.objects.create(
            field=field, label="Nuts", value="nuts", order=0
        )
        PersonalDataFieldOption.objects.create(
            field=field, label="Dairy", value="dairy", order=1
        )
        PersonalDataFieldRequirement.objects.create(
            category=proposal_category, field=field, is_required=False
        )
        self._set_wizard_category(authenticated_client, event, proposal_category)

        response = authenticated_client.post(
            self._get_category_url(event.slug), {"category_id": proposal_category.pk}
        )

        assert response.status_code == HTTPStatus.OK
        descriptors = response.context["field_descriptors"]
        assert len(descriptors) == 1
        assert descriptors[0]["is_multiple"] is True

    def test_post_session_multiple_select_field(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        field = SessionField.objects.create(
            event=event,
            name="Themes",
            question="What themes?",
            slug="themes",
            field_type="select",
            is_multiple=True,
        )
        SessionFieldOption.objects.create(
            field=field, label="Horror", value="horror", order=0
        )
        SessionFieldOption.objects.create(
            field=field, label="Comedy", value="comedy", order=1
        )
        SessionFieldRequirement.objects.create(
            category=proposal_category, field=field, is_required=False
        )
        self._set_wizard_category(authenticated_client, event, proposal_category)

        # Submit invalid to render session form with descriptors
        response = authenticated_client.post(self._get_details_url(event.slug), {})

        assert response.status_code == HTTPStatus.OK
        descriptors = response.context["field_descriptors"]
        assert len(descriptors) == 1
        assert descriptors[0]["is_multiple"] is True

    def test_submit_personal_data_with_non_personal_key_skipped(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        self._set_wizard_full(
            authenticated_client,
            event,
            proposal_category,
            personal_data={"other_key": "should be skipped"},
        )

        authenticated_client.post(self._get_submit_url(event.slug), {})

        assert HostPersonalData.objects.count() == 0

    # -- Coverage: checkbox field type (forms.py:44) --

    def test_post_personal_data_checkbox_field(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        field = PersonalDataField.objects.create(
            event=event,
            name="Agreement",
            question="Do you agree?",
            slug="agreement",
            field_type="checkbox",
        )
        PersonalDataFieldRequirement.objects.create(
            category=proposal_category, field=field, is_required=False
        )
        self._set_wizard_category(authenticated_client, event, proposal_category)

        response = authenticated_client.post(
            self._get_personal_url(event.slug),
            {"personal_agreement": "on", "contact_email": "test@example.com"},
        )

        assert response.status_code == HTTPStatus.OK
        wizard = authenticated_client.session[f"propose_{event.slug}"]
        assert wizard["personal_data"]["personal_agreement"] is True

    # -- Coverage: proposal_description in GET (views.py) --

    def test_get_shows_proposal_description(
        self, authenticated_client, event, faker, time_zone
    ):
        self._activate_proposals(event, faker, time_zone)
        EventProposalSettings.objects.create(event=event, description="## Welcome")
        ProposalCategoryFactory(event=event, name="RPG")

        response = authenticated_client.get(self._get_url(event.slug))

        assert response.status_code == HTTPStatus.OK
        content = response.content.decode()
        assert "<h2>Welcome</h2>" in content
        assert content.index("<h2>Welcome</h2>") < content.index(
            'aria-label="Proposal progress"'
        )

    # -- Coverage: proposal_description in category back (views.py) --

    def test_post_back_to_category_shows_proposal_description(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        EventProposalSettings.objects.create(event=event, description="## Rules")
        self._set_wizard_category(authenticated_client, event, proposal_category)

        response = authenticated_client.post(
            self._get_category_url(event.slug), {"back": "1"}
        )

        assert response.status_code == HTTPStatus.OK
        assert "<h2>Rules</h2>" in response.content.decode()

    # -- Coverage: personal data prefill from wizard session (views.py:119) --

    def test_personal_step_prefills_from_wizard_session(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        field = PersonalDataField.objects.create(
            event=event, name="Phone", question="What is your phone?", slug="phone"
        )
        PersonalDataFieldRequirement.objects.create(
            category=proposal_category, field=field, is_required=True
        )
        session = authenticated_client.session
        session[f"propose_{event.slug}"] = {
            "category_id": proposal_category.pk,
            "personal_data": {"personal_phone": "+48 777"},
            "contact_email": "wizard@example.com",
        }
        session.save()

        response = authenticated_client.post(
            self._get_personal_url(event.slug), {"back": "1"}
        )

        assert response.status_code == HTTPStatus.OK
        form = response.context["form"]
        assert form.initial["personal_phone"] == "+48 777"

    # -- Coverage: wizard stepper context (Fix D) --

    def test_category_step_exposes_stepper_context(
        self, authenticated_client, event, faker, time_zone
    ):
        self._activate_proposals(event, faker, time_zone)
        ProposalCategoryFactory(event=event)
        ProposalCategoryFactory(event=event)

        response = authenticated_client.post(self._get_category_url(event.slug), {})

        assert response.context["current_step"] == "category"
        assert [s["key"] for s in response.context["wizard_steps"]] == [
            "category",
            "personal",
            "timeslots",
            "details",
            "review",
        ]

    def test_personal_step_stepper_omits_timeslots_when_none_required(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        self._set_wizard_category(authenticated_client, event, proposal_category)

        response = authenticated_client.post(
            self._get_category_url(event.slug), {"category_id": proposal_category.pk}
        )

        assert response.context["current_step"] == "personal"
        assert [s["key"] for s in response.context["wizard_steps"]] == [
            "personal",
            "details",
            "review",
        ]

    def test_timeslots_step_stepper_includes_timeslots(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        slot1 = TimeSlotFactory(event=event)
        slot2 = TimeSlotFactory(
            event=event,
            start_time=event.start_time + timedelta(hours=3),
            end_time=event.start_time + timedelta(hours=5),
        )
        TimeSlotRequirement.objects.create(category=proposal_category, time_slot=slot1)
        TimeSlotRequirement.objects.create(category=proposal_category, time_slot=slot2)
        self._set_wizard_category(authenticated_client, event, proposal_category)

        response = authenticated_client.post(
            self._get_timeslots_url(event.slug), {"back": "1"}
        )

        assert response.context["current_step"] == "timeslots"
        assert [s["key"] for s in response.context["wizard_steps"]] == [
            "personal",
            "timeslots",
            "details",
            "review",
        ]

    def test_details_step_stepper_context(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        self._set_wizard_category(authenticated_client, event, proposal_category)

        response = authenticated_client.post(
            self._get_details_url(event.slug), {"back": "1"}
        )

        assert response.context["current_step"] == "details"
        assert [s["key"] for s in response.context["wizard_steps"]] == [
            "personal",
            "details",
            "review",
        ]

    def test_review_step_stepper_context(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        self._set_wizard_full(authenticated_client, event, proposal_category)

        response = authenticated_client.post(self._get_review_url(event.slug), {})

        assert response.context["current_step"] == "review"
        assert [s["key"] for s in response.context["wizard_steps"]] == [
            "personal",
            "details",
            "review",
        ]

    # -- Coverage: review formats boolean values (views.py:195-197, 203-205) --

    def test_review_formats_boolean_field_values(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        field = SessionField.objects.create(
            event=event,
            name="Needs projector",
            question="Do you need a projector?",
            slug="needs_projector",
            field_type="checkbox",
        )
        SessionFieldRequirement.objects.create(
            category=proposal_category, field=field, is_required=False
        )
        self._set_wizard_full(
            authenticated_client,
            event,
            proposal_category,
            session_data={
                "title": "Test Session",
                "participants_limit": 6,
                "session_needs_projector": True,
            },
        )

        response = authenticated_client.post(self._get_review_url(event.slug), {})

        review = response.context["review"]
        projector_field = next(
            f
            for f in review["session_fields"]
            if f["name"] == "Do you need a projector?"
        )
        assert projector_field["value"] is True

    # -- Coverage: review formats list values (views.py:201-202) --

    def test_review_formats_multiselect_field_values(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        field = SessionField.objects.create(
            event=event,
            name="Genres",
            question="What genres?",
            slug="genres",
            field_type="select",
            is_multiple=True,
        )
        SessionFieldOption.objects.create(field=field, value="fantasy", label="Fantasy")
        SessionFieldOption.objects.create(field=field, value="scifi", label="Sci-Fi")
        SessionFieldRequirement.objects.create(
            category=proposal_category, field=field, is_required=False
        )
        self._set_wizard_full(
            authenticated_client,
            event,
            proposal_category,
            session_data={
                "title": "Test Session",
                "participants_limit": 6,
                "session_genres": ["fantasy", "scifi"],
            },
        )

        response = authenticated_client.post(self._get_review_url(event.slug), {})

        review = response.context["review"]
        genre_field = next(
            f for f in review["session_fields"] if f["name"] == "What genres?"
        )
        assert genre_field["value"] == ["Fantasy", "Sci-Fi"]

    # -- Coverage: review resolves select slugs to human labels (Fix A) --

    def test_review_resolves_select_field_labels(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        field = SessionField.objects.create(
            event=event,
            name="System",
            question="Which system?",
            slug="system",
            field_type="select",
        )
        SessionFieldOption.objects.create(
            field=field, value="dnd5e", label="Dungeons & Dragons 5e"
        )
        SessionFieldRequirement.objects.create(
            category=proposal_category, field=field, is_required=False
        )
        self._set_wizard_full(
            authenticated_client,
            event,
            proposal_category,
            session_data={
                "title": "Test Session",
                "participants_limit": 6,
                "session_system": "dnd5e",
            },
        )

        response = authenticated_client.post(self._get_review_url(event.slug), {})

        review = response.context["review"]
        system_field = next(
            f for f in review["session_fields"] if f["name"] == "Which system?"
        )
        assert system_field["value"] == "Dungeons & Dragons 5e"

    # -- Coverage: custom-value fallthrough preserves typed text (Fix A) --

    def test_review_preserves_custom_typed_value(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        field = SessionField.objects.create(
            event=event,
            name="System",
            question="Which system?",
            slug="system",
            field_type="select",
            allow_custom=True,
        )
        SessionFieldOption.objects.create(field=field, value="dnd5e", label="D&D 5e")
        SessionFieldRequirement.objects.create(
            category=proposal_category, field=field, is_required=False
        )
        self._set_wizard_full(
            authenticated_client,
            event,
            proposal_category,
            session_data={
                "title": "Test Session",
                "participants_limit": 6,
                "session_system": "My Homebrew Game",
            },
        )

        response = authenticated_client.post(self._get_review_url(event.slug), {})

        review = response.context["review"]
        system_field = next(
            f for f in review["session_fields"] if f["name"] == "Which system?"
        )
        assert system_field["value"] == "My Homebrew Game"

    # -- Coverage: review passes raw string values through (views.py) --

    def test_review_passes_raw_string_values(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        field = SessionField.objects.create(
            event=event, name="Note", question="Any notes?", slug="note"
        )
        SessionFieldRequirement.objects.create(
            category=proposal_category, field=field, is_required=False
        )
        self._set_wizard_full(
            authenticated_client,
            event,
            proposal_category,
            session_data={
                "title": "Test Session",
                "participants_limit": 6,
                "session_note": "Some note",
            },
        )

        response = authenticated_client.post(self._get_review_url(event.slug), {})

        review = response.context["review"]
        note_field = next(
            f for f in review["session_fields"] if f["name"] == "Any notes?"
        )
        assert note_field["value"] == "Some note"

    # -- Coverage: review skips None values (views.py:193-194) --

    def test_review_skips_none_field_values(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        field = SessionField.objects.create(
            event=event,
            name="Optional",
            question="What is your optional info?",
            slug="optional",
        )
        SessionFieldRequirement.objects.create(
            category=proposal_category, field=field, is_required=False
        )
        # Don't include session_optional in wizard data — get() returns None
        self._set_wizard_full(authenticated_client, event, proposal_category)

        response = authenticated_client.post(self._get_review_url(event.slug), {})

        review = response.context["review"]
        field_names = [f["name"] for f in review["session_fields"]]
        assert "What is your optional info?" not in field_names

    # -- Coverage: review passes non-string/list/bool values through (views.py:112) --

    def test_review_passes_integer_field_values(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        field = SessionField.objects.create(
            event=event,
            name="Player Count",
            question="How many players?",
            slug="player-count",
        )
        SessionFieldRequirement.objects.create(
            category=proposal_category, field=field, is_required=False
        )
        integer_value = 42
        self._set_wizard_full(
            authenticated_client,
            event,
            proposal_category,
            session_data={
                "title": "Test Session",
                "participants_limit": 6,
                "session_player-count": integer_value,
            },
        )

        response = authenticated_client.post(self._get_review_url(event.slug), {})

        review = response.context["review"]
        player_count_field = next(
            f for f in review["session_fields"] if f["name"] == "How many players?"
        )
        assert player_count_field["value"] == integer_value

    # -- Coverage: review splits fields by public/private visibility --

    def test_review_separates_fields_by_visibility(
        self, authenticated_client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        public_sf = SessionField.objects.create(
            event=event,
            name="Genre",
            question="What genre?",
            slug="genre",
            is_public=True,
        )
        SessionFieldRequirement.objects.create(
            category=proposal_category, field=public_sf, is_required=False
        )
        private_sf = SessionField.objects.create(
            event=event,
            name="Notes",
            question="Internal notes?",
            slug="notes",
            is_public=False,
        )
        SessionFieldRequirement.objects.create(
            category=proposal_category, field=private_sf, is_required=False
        )
        public_pf = PersonalDataField.objects.create(
            event=event,
            name="Nickname",
            question="Your nickname?",
            slug="nickname",
            is_public=True,
        )
        PersonalDataFieldRequirement.objects.create(
            category=proposal_category, field=public_pf, is_required=False
        )
        private_pf = PersonalDataField.objects.create(
            event=event,
            name="Phone",
            question="Your phone?",
            slug="phone",
            is_public=False,
        )
        PersonalDataFieldRequirement.objects.create(
            category=proposal_category, field=private_pf, is_required=False
        )
        self._set_wizard_full(
            authenticated_client,
            event,
            proposal_category,
            session_data={
                "title": "Test Session",
                "participants_limit": 6,
                "session_genre": "RPG",
                "session_notes": "For organizers only",
            },
            personal_data={"personal_nickname": "Hero", "personal_phone": "+48 555"},
        )

        response = authenticated_client.post(self._get_review_url(event.slug), {})

        review = response.context["review"]
        all_sf_names = [f["name"] for f in review["session_fields"]]
        assert all_sf_names == ["What genre?", "Internal notes?"]
        private_sf_names = [f["name"] for f in review["private_session_fields"]]
        assert private_sf_names == ["Internal notes?"]
        public_pf_names = [f["name"] for f in review["public_personal_fields"]]
        assert public_pf_names == ["Your nickname?"]
        private_pf_names = [f["name"] for f in review["private_personal_fields"]]
        assert private_pf_names == ["Your phone?"]


class TestAnonymousProposalSubmission:
    """E2E tests for anonymous proposal submissions via Facilitator model."""

    URL_NAME = "web:chronology:session-propose"

    def _url(self, event_slug, step=""):
        name = f"{self.URL_NAME}-{step}" if step else self.URL_NAME
        return reverse(name, kwargs={"event_slug": event_slug})

    def _activate_proposals(self, event, faker, time_zone):
        event.proposal_start_time = faker.date_time_between(
            "-10d", "-1d", tzinfo=time_zone
        )
        event.proposal_end_time = faker.date_time_between(
            "+1d", "+10d", tzinfo=time_zone
        )
        event.save()

    def _enable_anonymous(self, event):
        EventProposalSettings.objects.update_or_create(
            event=event, defaults={"allow_anonymous_proposals": True}
        )

    def _set_wizard_full(self, client, event, category, **extra):
        session = client.session
        wizard = {
            "category_id": category.pk,
            "contact_email": "anon@example.com",
            "session_data": {
                "display_name": "Anonymous GM",
                "title": "Anon Session",
                "participants_limit": 6,
            },
            **extra,
        }
        session[f"propose_{event.slug}"] = wizard
        session.save()

    def test_anonymous_redirected_to_login_when_not_allowed(
        self, client, event, faker, time_zone
    ):
        self._activate_proposals(event, faker, time_zone)

        response = client.get(self._url(event.slug))

        assert response.status_code == HTTPStatus.FOUND
        assert "login" in response.url

    def test_anonymous_redirects_to_index_when_event_not_found(self, client):
        response = client.get(self._url("does-not-exist"))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url=reverse("web:index"),
        )

    def test_anonymous_redirects_to_event_when_proposals_inactive(self, client, event):
        response = client.get(self._url(event.slug))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.ERROR,
                    "Proposal submission is not currently active for this event.",
                )
            ],
            url=reverse("web:chronology:event", kwargs={"slug": event.slug}),
        )

    def test_anonymous_full_wizard_flow(
        self, client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        self._enable_anonymous(event)
        phone_field = PersonalDataField.objects.create(
            event=event, name="Phone", question="Your phone?", slug="phone"
        )
        PersonalDataFieldRequirement.objects.create(
            category=proposal_category, field=phone_field, is_required=True
        )

        # Step 1: GET landing page — see categories
        response = client.get(self._url(event.slug))
        assert response.status_code == HTTPStatus.OK

        # Step 2: POST category selection
        response = client.post(
            self._url(event.slug, "category"), {"category_id": proposal_category.pk}
        )
        assert response.status_code == HTTPStatus.OK

        # Step 3: POST personal data
        response = client.post(
            self._url(event.slug, "personal"),
            {"contact_email": "anon@example.com", "personal_phone": "+48 555"},
        )
        assert response.status_code == HTTPStatus.OK

        # Step 4: POST session details (no timeslots configured, skips to details)
        expected_limit = proposal_category.min_participants_limit
        response = client.post(
            self._url(event.slug, "details"),
            {
                "display_name": "Anonymous GM",
                "title": "My Anonymous Game",
                "description": "A fun game for everyone",
                "participants_limit": expected_limit,
            },
        )
        assert response.status_code == HTTPStatus.OK

        # Step 5: POST submit
        response = client.post(self._url(event.slug, "submit"))
        assert response.status_code == HTTPStatus.FOUND

        # Verify: Session created with no presenter
        session = Session.objects.get(title="My Anonymous Game")
        assert session.display_name == "Anonymous GM"
        assert session.presenter_id is None
        assert session.status == "pending"
        assert session.participants_limit == expected_limit

        # Verify: Facilitator created without user link
        facilitator = Facilitator.objects.get(event=event, display_name="Anonymous GM")
        assert facilitator.user_id is None
        assert facilitator.event_id == event.pk

        # Verify: Session linked to the Facilitator via M2M
        assert list(session.facilitators.values_list("pk", flat=True)) == [
            facilitator.pk
        ]

        # Verify: Personal data saved on facilitator, not on user
        hpd = HostPersonalData.objects.get(
            facilitator=facilitator, event=event, field=phone_field
        )
        assert hpd.value == "+48 555"
        assert hpd.user_id is None

    def test_anonymous_single_category_shows_login_nudge(
        self, client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        self._enable_anonymous(event)

        response = client.get(self._url(event.slug))
        form = response.context["form"]

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "event": EventDTO.model_validate(event),
                "category": ProposalCategoryDTO.model_validate(proposal_category),
                "proposal_settings": EventProposalSettingsDTO.model_validate(
                    EventProposalSettings.objects.get(event=event)
                ),
                "form": form,
                "field_descriptors": [],
                "current_step": "personal",
                "wizard_steps": [
                    {"key": "personal"},
                    {"key": "details"},
                    {"key": "review"},
                ],
                "show_back_button": False,
                "show_login_nudge": True,
                "login_url": f"/crowd/login-required/?next={self._url(event.slug)}",
                "wizard_part_template": "chronology/propose/parts/personal.html",
            },
            template_name="chronology/propose/base.html",
        )
        assert b"Have an account?" in response.content

    def test_anonymous_submit_blocked_by_rate_limit(
        self, client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        self._enable_anonymous(event)
        self._set_wizard_full(client, event, proposal_category)

        with patch(
            "ludamus.gates.web.django.chronology.views.check_proposal_rate_limit",
            return_value=False,
        ):
            response = client.post(self._url(event.slug, "submit"))

        assert response.status_code == HTTPStatus.FOUND
        assert Session.objects.count() == 0

    def test_two_anonymous_submissions_same_display_name_get_distinct_slugs(
        self, client, event, faker, time_zone, proposal_category
    ):
        self._activate_proposals(event, faker, time_zone)
        self._enable_anonymous(event)

        with patch(
            "ludamus.gates.web.django.chronology.views.check_proposal_rate_limit",
            return_value=True,
        ):
            self._set_wizard_full(client, event, proposal_category)
            first = client.post(self._url(event.slug, "submit"))
            assert first.status_code == HTTPStatus.FOUND

            self._set_wizard_full(client, event, proposal_category)
            second = client.post(self._url(event.slug, "submit"))
            assert second.status_code == HTTPStatus.FOUND

        expected_facilitator_count = 2
        facilitators = Facilitator.objects.filter(
            event=event, display_name="Anonymous GM"
        )
        assert facilitators.count() == expected_facilitator_count
        slugs = list(facilitators.values_list("slug", flat=True))
        assert len(set(slugs)) == expected_facilitator_count
