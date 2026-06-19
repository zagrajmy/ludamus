from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import (
    HostPersonalData,
    PersonalDataField,
    PersonalDataFieldRequirement,
    ProposalCategory,
    SessionField,
    SessionFieldRequirement,
    TimeSlot,
    TimeSlotRequirement,
)
from ludamus.pacts import (
    EventDTO,
    PersonalDataFieldDTO,
    ProposalCategoryDTO,
    SessionFieldDTO,
    TimeSlotDTO,
)
from tests.integration.conftest import EventFactory, SessionFactory, UserFactory
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


class TestCFPEditPageView:
    """Tests for /panel/event/<slug>/cfp/<category_slug>/ page."""

    @staticmethod
    def get_url(event, category):
        return reverse(
            "panel:cfp-edit",
            kwargs={"event_slug": event.slug, "category_slug": category.slug},
        )

    # GET tests

    def test_get_redirects_anonymous_user_to_login(self, client, event):
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        url = self.get_url(event, category)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_get_redirects_non_manager_user(self, authenticated_client, event):
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )

        response = authenticated_client.get(self.get_url(event, category))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_get_ok_for_sphere_manager(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )

        response = authenticated_client.get(self.get_url(event, category))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/cfp-edit.html",
            context_data={
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
                "active_nav": "cfp",
                "category": ProposalCategoryDTO.model_validate(category),
                "form": ANY,
                "available_fields": [],
                "field_requirements": {},
                "field_order": [],
                "available_session_fields": [],
                "session_field_requirements": {},
                "session_field_order": [],
                "available_time_slots": [],
                "time_slot_requirements": {},
                "time_slot_order": [],
                "durations": [],
                "proposal_count": 0,
            },
        )

    def test_get_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse(
            "panel:cfp-edit",
            kwargs={"event_slug": "nonexistent", "category_slug": "any"},
        )

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_get_redirects_on_invalid_category_slug(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        url = reverse(
            "panel:cfp-edit",
            kwargs={"event_slug": event.slug, "category_slug": "nonexistent"},
        )

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Session type not found.")],
            url=f"/panel/event/{event.slug}/cfp/",
        )

    # POST tests

    def test_post_redirects_anonymous_user_to_login(self, client, event):
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        url = self.get_url(event, category)

        response = client.post(url, data={"name": "Workshops"})

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_post_redirects_non_manager_user(self, authenticated_client, event):
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )

        response = authenticated_client.post(
            self.get_url(event, category), data={"name": "Workshops"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_post_updates_category_for_sphere_manager(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )

        response = authenticated_client.post(
            self.get_url(event, category), data={"name": "Workshops"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Session type updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/",
        )
        category.refresh_from_db()
        assert category.name == "Workshops"
        assert category.slug == "workshops"

    def test_post_generates_unique_slug_on_collision(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        ProposalCategory.objects.create(event=event, name="Workshops", slug="workshops")
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )

        authenticated_client.post(
            self.get_url(event, category), data={"name": "Workshops"}
        )

        category.refresh_from_db()
        assert category.name == "Workshops"
        assert category.slug.startswith("workshops-")

    def test_post_keeps_slug_if_name_unchanged(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )

        authenticated_client.post(
            self.get_url(event, category), data={"name": "RPG Sessions"}
        )

        category.refresh_from_db()
        assert category.name == "RPG Sessions"
        assert category.slug == "rpg-sessions"

    def test_post_error_on_empty_name_rerenders_form(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )

        response = authenticated_client.post(self.get_url(event, category), data={})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/cfp-edit.html",
            context_data={
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
                "active_nav": "cfp",
                "category": ProposalCategoryDTO.model_validate(category),
                "form": ANY,
                "field_order": [],
                "field_requirements": {},
                "proposal_count": 0,
                "session_field_order": [],
                "session_field_requirements": {},
                "available_fields": [],
                "available_session_fields": [],
                "available_time_slots": [],
                "time_slot_requirements": {},
                "time_slot_order": [],
                "durations": [],
            },
        )
        category.refresh_from_db()
        assert category.name == "RPG Sessions"

    def test_post_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse(
            "panel:cfp-edit",
            kwargs={"event_slug": "nonexistent", "category_slug": "any"},
        )

        response = authenticated_client.post(url, data={"name": "Workshops"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_post_redirects_on_invalid_category_slug(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        url = reverse(
            "panel:cfp-edit",
            kwargs={"event_slug": event.slug, "category_slug": "nonexistent"},
        )

        response = authenticated_client.post(url, data={"name": "Workshops"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Session type not found.")],
            url=f"/panel/event/{event.slug}/cfp/",
        )

    # Time fields tests

    def test_get_form_contains_time_fields_with_initial_values(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        start = datetime(2025, 3, 1, 10, 0, tzinfo=UTC)
        end = datetime(2025, 4, 30, 23, 59, tzinfo=UTC)
        category = ProposalCategory.objects.create(
            event=event,
            name="RPG Sessions",
            slug="rpg-sessions",
            start_time=start,
            end_time=end,
        )

        response = authenticated_client.get(self.get_url(event, category))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/cfp-edit.html",
            context_data={
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
                "active_nav": "cfp",
                "category": ProposalCategoryDTO.model_validate(category),
                "form": ANY,
                "available_fields": [],
                "field_requirements": {},
                "field_order": [],
                "available_session_fields": [],
                "session_field_requirements": {},
                "session_field_order": [],
                "available_time_slots": [],
                "time_slot_requirements": {},
                "time_slot_order": [],
                "durations": [],
                "proposal_count": 0,
            },
        )

    def test_post_updates_time_fields(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )

        response = authenticated_client.post(
            self.get_url(event, category),
            data={
                "name": "RPG Sessions",
                "start_time": "2025-03-01T10:00",
                "end_time": "2025-04-30T23:59",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Session type updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/",
        )
        category.refresh_from_db()
        assert category.start_time is not None
        assert category.start_time.date() == datetime(2025, 3, 1, tzinfo=UTC).date()
        assert category.end_time is not None
        assert category.end_time.date() == datetime(2025, 4, 30, tzinfo=UTC).date()

    def test_post_clears_time_fields_when_empty(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event,
            name="RPG Sessions",
            slug="rpg-sessions",
            start_time=datetime(2025, 3, 1, 10, 0, tzinfo=UTC),
            end_time=datetime(2025, 4, 30, 23, 59, tzinfo=UTC),
        )

        response = authenticated_client.post(
            self.get_url(event, category),
            data={"name": "RPG Sessions", "start_time": "", "end_time": ""},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Session type updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/",
        )
        category.refresh_from_db()
        assert category.start_time is None
        assert category.end_time is None

    # Field requirements tests

    def test_get_includes_available_fields_in_context(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        email_field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )
        phone_field = PersonalDataField.objects.create(
            event=event, name="Phone", question="What is your phone?", slug="phone"
        )

        response = authenticated_client.get(self.get_url(event, category))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/cfp-edit.html",
            context_data={
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
                "active_nav": "cfp",
                "category": ProposalCategoryDTO.model_validate(category),
                "form": ANY,
                "available_fields": [
                    PersonalDataFieldDTO(
                        pk=email_field.pk,
                        name="Email",
                        question="What is your email?",
                        slug="email",
                        field_type="text",
                        order=0,
                        options=[],
                    ),
                    PersonalDataFieldDTO(
                        pk=phone_field.pk,
                        name="Phone",
                        question="What is your phone?",
                        slug="phone",
                        field_type="text",
                        order=0,
                        options=[],
                    ),
                ],
                "field_requirements": {},
                "field_order": [],
                "available_session_fields": [],
                "session_field_requirements": {},
                "session_field_order": [],
                "available_time_slots": [],
                "time_slot_requirements": {},
                "time_slot_order": [],
                "durations": [],
                "proposal_count": 0,
            },
        )

    def test_get_includes_field_requirements_in_context(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        email_field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )
        phone_field = PersonalDataField.objects.create(
            event=event, name="Phone", question="What is your phone?", slug="phone"
        )
        PersonalDataFieldRequirement.objects.create(
            category=category, field=email_field, is_required=True
        )
        PersonalDataFieldRequirement.objects.create(
            category=category, field=phone_field, is_required=False
        )

        response = authenticated_client.get(self.get_url(event, category))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/cfp-edit.html",
            context_data={
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
                "active_nav": "cfp",
                "category": ProposalCategoryDTO.model_validate(category),
                "form": ANY,
                "available_fields": [
                    PersonalDataFieldDTO(
                        pk=email_field.pk,
                        name="Email",
                        question="What is your email?",
                        slug="email",
                        field_type="text",
                        order=0,
                        options=[],
                    ),
                    PersonalDataFieldDTO(
                        pk=phone_field.pk,
                        name="Phone",
                        question="What is your phone?",
                        slug="phone",
                        field_type="text",
                        order=0,
                        options=[],
                    ),
                ],
                "field_requirements": {email_field.pk: True, phone_field.pk: False},
                "field_order": [email_field.pk, phone_field.pk],
                "available_session_fields": [],
                "session_field_requirements": {},
                "session_field_order": [],
                "available_time_slots": [],
                "time_slot_requirements": {},
                "time_slot_order": [],
                "durations": [],
                "proposal_count": 0,
            },
        )

    def test_get_returns_empty_field_requirements_when_none_configured(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        email_field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )

        response = authenticated_client.get(self.get_url(event, category))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/cfp-edit.html",
            context_data={
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
                "active_nav": "cfp",
                "category": ProposalCategoryDTO.model_validate(category),
                "form": ANY,
                "available_fields": [
                    PersonalDataFieldDTO(
                        pk=email_field.pk,
                        name="Email",
                        question="What is your email?",
                        slug="email",
                        field_type="text",
                        order=0,
                        options=[],
                    )
                ],
                "field_requirements": {},
                "field_order": [],
                "available_session_fields": [],
                "session_field_requirements": {},
                "session_field_order": [],
                "available_time_slots": [],
                "time_slot_requirements": {},
                "time_slot_order": [],
                "durations": [],
                "proposal_count": 0,
            },
        )

    def test_post_drops_requirement_pks_from_another_event(
        self, authenticated_client, active_user, sphere, event
    ):
        """Field/session-field/time-slot pks from another event are not linked."""
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        other_event = EventFactory(sphere=sphere)
        foreign_field = PersonalDataField.objects.create(
            event=other_event, name="Email", question="?", slug="email"
        )
        foreign_session_field = SessionField.objects.create(
            event=other_event, name="Genre", question="?", slug="genre"
        )
        foreign_slot = TimeSlot.objects.create(
            event=other_event,
            start_time=other_event.start_time,
            end_time=other_event.start_time + timedelta(hours=1),
        )

        response = authenticated_client.post(
            self.get_url(event, category),
            data={
                "name": "RPG Sessions",
                f"field_{foreign_field.pk}": "required",
                f"session_field_{foreign_session_field.pk}": "required",
                f"time_slot_{foreign_slot.pk}": "required",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Session type updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/",
        )
        assert not PersonalDataFieldRequirement.objects.filter(
            category=category, field=foreign_field
        ).exists()
        assert not SessionFieldRequirement.objects.filter(
            category=category, field=foreign_session_field
        ).exists()
        assert not TimeSlotRequirement.objects.filter(
            category=category, time_slot=foreign_slot
        ).exists()

    def test_post_saves_field_requirement_as_required(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        email_field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )

        response = authenticated_client.post(
            self.get_url(event, category),
            data={"name": "RPG Sessions", f"field_{email_field.pk}": "required"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Session type updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/",
        )
        requirement = PersonalDataFieldRequirement.objects.get(
            category=category, field=email_field
        )
        assert requirement.is_required is True

    def test_post_saves_field_requirement_as_optional(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        phone_field = PersonalDataField.objects.create(
            event=event, name="Phone", question="What is your phone?", slug="phone"
        )

        response = authenticated_client.post(
            self.get_url(event, category),
            data={"name": "RPG Sessions", f"field_{phone_field.pk}": "optional"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Session type updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/",
        )
        requirement = PersonalDataFieldRequirement.objects.get(
            category=category, field=phone_field
        )
        assert requirement.is_required is False

    def test_post_removes_field_requirement_when_set_to_none(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        email_field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )
        PersonalDataFieldRequirement.objects.create(
            category=category, field=email_field, is_required=True
        )

        response = authenticated_client.post(
            self.get_url(event, category),
            data={"name": "RPG Sessions", f"field_{email_field.pk}": "none"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Session type updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/",
        )
        assert not PersonalDataFieldRequirement.objects.filter(
            category=category, field=email_field
        ).exists()

    def test_post_updates_existing_requirement_from_required_to_optional(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        email_field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )
        PersonalDataFieldRequirement.objects.create(
            category=category, field=email_field, is_required=True
        )

        response = authenticated_client.post(
            self.get_url(event, category),
            data={"name": "RPG Sessions", f"field_{email_field.pk}": "optional"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Session type updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/",
        )
        requirement = PersonalDataFieldRequirement.objects.get(
            category=category, field=email_field
        )
        assert requirement.is_required is False

    def test_post_saves_multiple_field_requirements(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        email_field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )
        phone_field = PersonalDataField.objects.create(
            event=event, name="Phone", question="What is your phone?", slug="phone"
        )
        bio_field = PersonalDataField.objects.create(
            event=event, name="Bio", question="Tell us about yourself", slug="bio"
        )

        response = authenticated_client.post(
            self.get_url(event, category),
            data={
                "name": "RPG Sessions",
                f"field_{email_field.pk}": "required",
                f"field_{phone_field.pk}": "optional",
                f"field_{bio_field.pk}": "none",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Session type updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/",
        )
        assert (
            PersonalDataFieldRequirement.objects.filter(category=category).count()
            == 1 + 1  # email + phone (bio is "none")
        )
        email_req = PersonalDataFieldRequirement.objects.get(
            category=category, field=email_field
        )
        phone_req = PersonalDataFieldRequirement.objects.get(
            category=category, field=phone_field
        )
        assert email_req.is_required is True
        assert phone_req.is_required is False
        assert not PersonalDataFieldRequirement.objects.filter(
            category=category, field=bio_field
        ).exists()

    # Duration configuration tests

    def test_get_includes_durations_in_context(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event,
            name="RPG Sessions",
            slug="rpg-sessions",
            durations=["PT1H", "PT2H", "PT3H"],
        )

        response = authenticated_client.get(self.get_url(event, category))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/cfp-edit.html",
            context_data={
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
                "active_nav": "cfp",
                "category": ProposalCategoryDTO.model_validate(category),
                "form": ANY,
                "available_fields": [],
                "field_requirements": {},
                "field_order": [],
                "available_session_fields": [],
                "session_field_requirements": {},
                "session_field_order": [],
                "available_time_slots": [],
                "time_slot_requirements": {},
                "time_slot_order": [],
                "durations": ["PT1H", "PT2H", "PT3H"],
                "proposal_count": 0,
            },
        )

    def test_get_returns_empty_durations_when_none_configured(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )

        response = authenticated_client.get(self.get_url(event, category))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/cfp-edit.html",
            context_data={
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
                "active_nav": "cfp",
                "category": ProposalCategoryDTO.model_validate(category),
                "form": ANY,
                "available_fields": [],
                "field_requirements": {},
                "field_order": [],
                "available_session_fields": [],
                "session_field_requirements": {},
                "session_field_order": [],
                "available_time_slots": [],
                "time_slot_requirements": {},
                "time_slot_order": [],
                "durations": [],
                "proposal_count": 0,
            },
        )

    def test_post_saves_durations(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )

        response = authenticated_client.post(
            self.get_url(event, category),
            data={"name": "RPG Sessions", "durations": ["PT30M", "PT1H", "PT2H"]},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Session type updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/",
        )
        category.refresh_from_db()
        assert category.durations == ["PT30M", "PT1H", "PT2H"]

    def test_post_updates_existing_durations(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event,
            name="RPG Sessions",
            slug="rpg-sessions",
            durations=["PT1H", "PT2H"],
        )

        response = authenticated_client.post(
            self.get_url(event, category),
            data={"name": "RPG Sessions", "durations": ["PT30M", "PT45M"]},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Session type updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/",
        )
        category.refresh_from_db()
        assert category.durations == ["PT30M", "PT45M"]

    def test_post_clears_durations_when_empty(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event,
            name="RPG Sessions",
            slug="rpg-sessions",
            durations=["PT1H", "PT2H"],
        )

        response = authenticated_client.post(
            self.get_url(event, category), data={"name": "RPG Sessions"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Session type updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/",
        )
        category.refresh_from_db()
        assert category.durations == []

    def test_post_saves_single_duration(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )

        response = authenticated_client.post(
            self.get_url(event, category),
            data={
                "name": "RPG Sessions",
                "durations": "PT1H",  # Single value (not list)
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Session type updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/",
        )
        category.refresh_from_db()
        assert category.durations == ["PT1H"]

    # Session field requirements tests

    def test_get_includes_available_session_fields_in_context(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        genre_field = SessionField.objects.create(
            event=event, name="Genre", question="What genre?", slug="genre"
        )
        difficulty_field = SessionField.objects.create(
            event=event,
            name="Difficulty",
            question="What difficulty level?",
            slug="difficulty",
        )

        response = authenticated_client.get(self.get_url(event, category))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/cfp-edit.html",
            context_data={
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
                "active_nav": "cfp",
                "category": ProposalCategoryDTO.model_validate(category),
                "form": ANY,
                "available_fields": [],
                "field_requirements": {},
                "field_order": [],
                "available_session_fields": [
                    SessionFieldDTO(
                        pk=difficulty_field.pk,
                        name="Difficulty",
                        question="What difficulty level?",
                        slug="difficulty",
                        field_type="text",
                        order=0,
                        options=[],
                    ),
                    SessionFieldDTO(
                        pk=genre_field.pk,
                        name="Genre",
                        question="What genre?",
                        slug="genre",
                        field_type="text",
                        order=0,
                        options=[],
                    ),
                ],
                "session_field_requirements": {},
                "session_field_order": [],
                "available_time_slots": [],
                "time_slot_requirements": {},
                "time_slot_order": [],
                "durations": [],
                "proposal_count": 0,
            },
        )

    def test_get_includes_session_field_requirements_in_context(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        genre_field = SessionField.objects.create(
            event=event, name="Genre", question="What genre?", slug="genre"
        )
        difficulty_field = SessionField.objects.create(
            event=event,
            name="Difficulty",
            question="What difficulty level?",
            slug="difficulty",
        )
        SessionFieldRequirement.objects.create(
            category=category, field=genre_field, is_required=True
        )
        SessionFieldRequirement.objects.create(
            category=category, field=difficulty_field, is_required=False
        )

        response = authenticated_client.get(self.get_url(event, category))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/cfp-edit.html",
            context_data={
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
                "active_nav": "cfp",
                "category": ProposalCategoryDTO.model_validate(category),
                "form": ANY,
                "available_fields": [],
                "field_requirements": {},
                "field_order": [],
                "available_session_fields": [
                    SessionFieldDTO(
                        pk=genre_field.pk,
                        name="Genre",
                        question="What genre?",
                        slug="genre",
                        field_type="text",
                        order=0,
                        options=[],
                    ),
                    SessionFieldDTO(
                        pk=difficulty_field.pk,
                        name="Difficulty",
                        question="What difficulty level?",
                        slug="difficulty",
                        field_type="text",
                        order=0,
                        options=[],
                    ),
                ],
                "session_field_requirements": {
                    genre_field.pk: True,
                    difficulty_field.pk: False,
                },
                "session_field_order": [genre_field.pk, difficulty_field.pk],
                "available_time_slots": [],
                "time_slot_requirements": {},
                "time_slot_order": [],
                "durations": [],
                "proposal_count": 0,
            },
        )

    def test_get_returns_empty_session_field_requirements_when_none_configured(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        genre_field = SessionField.objects.create(
            event=event, name="Genre", question="What genre?", slug="genre"
        )

        response = authenticated_client.get(self.get_url(event, category))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/cfp-edit.html",
            context_data={
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
                "active_nav": "cfp",
                "category": ProposalCategoryDTO.model_validate(category),
                "form": ANY,
                "available_fields": [],
                "field_requirements": {},
                "field_order": [],
                "available_session_fields": [
                    SessionFieldDTO(
                        pk=genre_field.pk,
                        name="Genre",
                        question="What genre?",
                        slug="genre",
                        field_type="text",
                        order=0,
                        options=[],
                    )
                ],
                "session_field_requirements": {},
                "session_field_order": [],
                "available_time_slots": [],
                "time_slot_requirements": {},
                "time_slot_order": [],
                "durations": [],
                "proposal_count": 0,
            },
        )

    def test_post_saves_session_field_requirement_as_required(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        genre_field = SessionField.objects.create(
            event=event, name="Genre", question="What genre?", slug="genre"
        )

        response = authenticated_client.post(
            self.get_url(event, category),
            data={
                "name": "RPG Sessions",
                f"session_field_{genre_field.pk}": "required",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Session type updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/",
        )
        requirement = SessionFieldRequirement.objects.get(
            category=category, field=genre_field
        )
        assert requirement.is_required is True

    def test_post_saves_session_field_requirement_as_optional(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        genre_field = SessionField.objects.create(
            event=event, name="Genre", question="What genre?", slug="genre"
        )

        response = authenticated_client.post(
            self.get_url(event, category),
            data={
                "name": "RPG Sessions",
                f"session_field_{genre_field.pk}": "optional",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Session type updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/",
        )
        requirement = SessionFieldRequirement.objects.get(
            category=category, field=genre_field
        )
        assert requirement.is_required is False

    def test_post_removes_session_field_requirement_when_set_to_none(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        genre_field = SessionField.objects.create(
            event=event, name="Genre", question="What genre?", slug="genre"
        )
        SessionFieldRequirement.objects.create(
            category=category, field=genre_field, is_required=True
        )

        response = authenticated_client.post(
            self.get_url(event, category),
            data={"name": "RPG Sessions", f"session_field_{genre_field.pk}": "none"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Session type updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/",
        )
        assert not SessionFieldRequirement.objects.filter(
            category=category, field=genre_field
        ).exists()

    def test_post_saves_multiple_session_field_requirements(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        genre_field = SessionField.objects.create(
            event=event, name="Genre", question="What genre?", slug="genre"
        )
        difficulty_field = SessionField.objects.create(
            event=event,
            name="Difficulty",
            question="What difficulty level?",
            slug="difficulty",
        )
        system_field = SessionField.objects.create(
            event=event,
            name="System",
            question="What RPG system will you use?",
            slug="system",
        )

        response = authenticated_client.post(
            self.get_url(event, category),
            data={
                "name": "RPG Sessions",
                f"session_field_{genre_field.pk}": "required",
                f"session_field_{difficulty_field.pk}": "optional",
                f"session_field_{system_field.pk}": "none",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Session type updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/",
        )
        assert (
            SessionFieldRequirement.objects.filter(category=category).count()
            == 1 + 1  # genre + difficulty (system is "none")
        )
        genre_req = SessionFieldRequirement.objects.get(
            category=category, field=genre_field
        )
        difficulty_req = SessionFieldRequirement.objects.get(
            category=category, field=difficulty_field
        )
        assert genre_req.is_required is True
        assert difficulty_req.is_required is False
        assert not SessionFieldRequirement.objects.filter(
            category=category, field=system_field
        ).exists()

    # Field ordering tests

    def test_get_includes_field_order_in_context(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        email_field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )
        phone_field = PersonalDataField.objects.create(
            event=event, name="Phone", question="What is your phone?", slug="phone"
        )
        PersonalDataFieldRequirement.objects.create(
            category=category, field=email_field, is_required=True, order=1
        )
        PersonalDataFieldRequirement.objects.create(
            category=category, field=phone_field, is_required=False, order=0
        )

        response = authenticated_client.get(self.get_url(event, category))

        # Order should be [phone, email] based on order field
        # (phone has order=0, email has order=1)
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/cfp-edit.html",
            context_data={
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
                "active_nav": "cfp",
                "category": ProposalCategoryDTO.model_validate(category),
                "form": ANY,
                "available_fields": [
                    PersonalDataFieldDTO(
                        pk=phone_field.pk,
                        name="Phone",
                        question="What is your phone?",
                        slug="phone",
                        field_type="text",
                        order=0,
                        options=[],
                    ),
                    PersonalDataFieldDTO(
                        pk=email_field.pk,
                        name="Email",
                        question="What is your email?",
                        slug="email",
                        field_type="text",
                        order=0,
                        options=[],
                    ),
                ],
                "field_requirements": {email_field.pk: True, phone_field.pk: False},
                "field_order": [phone_field.pk, email_field.pk],
                "available_session_fields": [],
                "session_field_requirements": {},
                "session_field_order": [],
                "available_time_slots": [],
                "time_slot_requirements": {},
                "time_slot_order": [],
                "durations": [],
                "proposal_count": 0,
            },
        )

    def test_get_places_new_fields_after_ordered_fields(
        self, authenticated_client, active_user, sphere, event
    ):
        """New fields not in saved order should appear after ordered fields."""
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        email_field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )
        phone_field = PersonalDataField.objects.create(
            event=event, name="Phone", question="What is your phone?", slug="phone"
        )
        # Only email has a saved order requirement
        PersonalDataFieldRequirement.objects.create(
            category=category, field=email_field, is_required=True, order=0
        )
        # Phone is available but NOT in order (simulates new field added)

        response = authenticated_client.get(self.get_url(event, category))

        # Email should be first (has order),
        # Phone should be after - verified by field_order
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/cfp-edit.html",
            context_data={
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
                "active_nav": "cfp",
                "category": ProposalCategoryDTO.model_validate(category),
                "form": ANY,
                "available_fields": [
                    PersonalDataFieldDTO(
                        pk=email_field.pk,
                        name="Email",
                        question="What is your email?",
                        slug="email",
                        field_type="text",
                        order=0,
                        options=[],
                    ),
                    PersonalDataFieldDTO(
                        pk=phone_field.pk,
                        name="Phone",
                        question="What is your phone?",
                        slug="phone",
                        field_type="text",
                        order=0,
                        options=[],
                    ),
                ],
                "field_requirements": {email_field.pk: True},
                "field_order": [email_field.pk],
                "available_session_fields": [],
                "session_field_requirements": {},
                "session_field_order": [],
                "available_time_slots": [],
                "time_slot_requirements": {},
                "time_slot_order": [],
                "durations": [],
                "proposal_count": 0,
            },
        )

    def test_get_returns_empty_field_order_when_none_configured(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )

        response = authenticated_client.get(self.get_url(event, category))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/cfp-edit.html",
            context_data={
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
                "active_nav": "cfp",
                "category": ProposalCategoryDTO.model_validate(category),
                "form": ANY,
                "available_fields": [],
                "field_requirements": {},
                "field_order": [],
                "available_session_fields": [],
                "session_field_requirements": {},
                "session_field_order": [],
                "available_time_slots": [],
                "time_slot_requirements": {},
                "time_slot_order": [],
                "durations": [],
                "proposal_count": 0,
            },
        )

    def test_post_saves_field_order(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        email_field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )
        phone_field = PersonalDataField.objects.create(
            event=event, name="Phone", question="What is your phone?", slug="phone"
        )

        response = authenticated_client.post(
            self.get_url(event, category),
            data={
                "name": "RPG Sessions",
                f"field_{email_field.pk}": "required",
                f"field_{phone_field.pk}": "optional",
                "field_order": f"{phone_field.pk},{email_field.pk}",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Session type updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/",
        )
        email_req = PersonalDataFieldRequirement.objects.get(
            category=category, field=email_field
        )
        phone_req = PersonalDataFieldRequirement.objects.get(
            category=category, field=phone_field
        )
        assert phone_req.order == 0
        assert email_req.order == 1

    def test_get_includes_session_field_order_in_context(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        genre_field = SessionField.objects.create(
            event=event, name="Genre", question="What genre?", slug="genre"
        )
        difficulty_field = SessionField.objects.create(
            event=event,
            name="Difficulty",
            question="What difficulty level?",
            slug="difficulty",
        )
        SessionFieldRequirement.objects.create(
            category=category, field=genre_field, is_required=True, order=1
        )
        SessionFieldRequirement.objects.create(
            category=category, field=difficulty_field, is_required=False, order=0
        )

        response = authenticated_client.get(self.get_url(event, category))

        # Order should be [difficulty, genre] based on order field
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/cfp-edit.html",
            context_data={
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
                "active_nav": "cfp",
                "category": ProposalCategoryDTO.model_validate(category),
                "form": ANY,
                "available_fields": [],
                "field_requirements": {},
                "field_order": [],
                "available_session_fields": [
                    SessionFieldDTO(
                        pk=difficulty_field.pk,
                        name="Difficulty",
                        question="What difficulty level?",
                        slug="difficulty",
                        field_type="text",
                        order=0,
                        options=[],
                    ),
                    SessionFieldDTO(
                        pk=genre_field.pk,
                        name="Genre",
                        question="What genre?",
                        slug="genre",
                        field_type="text",
                        order=0,
                        options=[],
                    ),
                ],
                "session_field_requirements": {
                    genre_field.pk: True,
                    difficulty_field.pk: False,
                },
                "session_field_order": [difficulty_field.pk, genre_field.pk],
                "available_time_slots": [],
                "time_slot_requirements": {},
                "time_slot_order": [],
                "durations": [],
                "proposal_count": 0,
            },
        )

    def test_get_places_new_session_fields_after_ordered_fields(
        self, authenticated_client, active_user, sphere, event
    ):
        """New session fields not in saved order should appear after ordered fields."""
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        genre_field = SessionField.objects.create(
            event=event, name="Genre", question="What genre?", slug="genre"
        )
        difficulty_field = SessionField.objects.create(
            event=event,
            name="Difficulty",
            question="What difficulty level?",
            slug="difficulty",
        )
        # Only genre has a saved order requirement
        SessionFieldRequirement.objects.create(
            category=category, field=genre_field, is_required=True, order=0
        )
        # Difficulty is available but NOT in order (simulates new field added)

        response = authenticated_client.get(self.get_url(event, category))

        # Genre should be first (has order), Difficulty should be after
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/cfp-edit.html",
            context_data={
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
                "active_nav": "cfp",
                "category": ProposalCategoryDTO.model_validate(category),
                "form": ANY,
                "available_fields": [],
                "field_requirements": {},
                "field_order": [],
                "available_session_fields": [
                    SessionFieldDTO(
                        pk=genre_field.pk,
                        name="Genre",
                        question="What genre?",
                        slug="genre",
                        field_type="text",
                        order=0,
                        options=[],
                    ),
                    SessionFieldDTO(
                        pk=difficulty_field.pk,
                        name="Difficulty",
                        question="What difficulty level?",
                        slug="difficulty",
                        field_type="text",
                        order=0,
                        options=[],
                    ),
                ],
                "session_field_requirements": {genre_field.pk: True},
                "session_field_order": [genre_field.pk],
                "available_time_slots": [],
                "time_slot_requirements": {},
                "time_slot_order": [],
                "durations": [],
                "proposal_count": 0,
            },
        )

    def test_get_returns_empty_session_field_order_when_none_configured(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )

        response = authenticated_client.get(self.get_url(event, category))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/cfp-edit.html",
            context_data={
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
                "active_nav": "cfp",
                "category": ProposalCategoryDTO.model_validate(category),
                "form": ANY,
                "available_fields": [],
                "field_requirements": {},
                "field_order": [],
                "available_session_fields": [],
                "session_field_requirements": {},
                "session_field_order": [],
                "available_time_slots": [],
                "time_slot_requirements": {},
                "time_slot_order": [],
                "durations": [],
                "proposal_count": 0,
            },
        )

    def test_post_saves_session_field_order(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        genre_field = SessionField.objects.create(
            event=event, name="Genre", question="What genre?", slug="genre"
        )
        difficulty_field = SessionField.objects.create(
            event=event,
            name="Difficulty",
            question="What difficulty level?",
            slug="difficulty",
        )

        response = authenticated_client.post(
            self.get_url(event, category),
            data={
                "name": "RPG Sessions",
                f"session_field_{genre_field.pk}": "required",
                f"session_field_{difficulty_field.pk}": "optional",
                "session_field_order": f"{difficulty_field.pk},{genre_field.pk}",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Session type updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/",
        )
        genre_req = SessionFieldRequirement.objects.get(
            category=category, field=genre_field
        )
        difficulty_req = SessionFieldRequirement.objects.get(
            category=category, field=difficulty_field
        )
        assert difficulty_req.order == 0
        assert genre_req.order == 1

    # Proposal count tests

    def test_get_includes_proposal_count_zero_when_no_proposals(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )

        response = authenticated_client.get(self.get_url(event, category))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/cfp-edit.html",
            context_data={
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
                "active_nav": "cfp",
                "category": ProposalCategoryDTO.model_validate(category),
                "form": ANY,
                "available_fields": [],
                "field_requirements": {},
                "field_order": [],
                "available_session_fields": [],
                "session_field_requirements": {},
                "session_field_order": [],
                "available_time_slots": [],
                "time_slot_requirements": {},
                "time_slot_order": [],
                "durations": [],
                "proposal_count": 0,
            },
        )

    def test_get_includes_proposal_count_with_existing_proposals(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        SessionFactory.create(category=category, sphere=sphere, status="pending")
        SessionFactory.create(category=category, sphere=sphere, status="pending")
        SessionFactory.create(category=category, sphere=sphere, status="pending")

        response = authenticated_client.get(self.get_url(event, category))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/cfp-edit.html",
            context_data={
                "current_event": EventDTO.model_validate(event),
                "events": [EventDTO.model_validate(event)],
                "is_proposal_active": False,
                "stats": {
                    "hosts_count": 1 + 1 + 1,  # 3 unique presenters
                    "pending_proposals": 1 + 1 + 1,  # 3 pending sessions
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 1 + 1 + 1,
                    "total_sessions": 1 + 1 + 1,  # pending + scheduled
                },
                "active_nav": "cfp",
                "category": ProposalCategoryDTO.model_validate(category),
                "form": ANY,
                "available_fields": [],
                "field_requirements": {},
                "field_order": [],
                "available_session_fields": [],
                "session_field_requirements": {},
                "session_field_order": [],
                "available_time_slots": [],
                "time_slot_requirements": {},
                "time_slot_order": [],
                "durations": [],
                "proposal_count": 1 + 1 + 1,  # 3 sessions created for this category
            },
        )

    def test_get_proposal_count_only_counts_proposals_for_this_category(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        other_category = ProposalCategory.objects.create(
            event=event, name="Workshops", slug="workshops"
        )
        SessionFactory.create(category=category, sphere=sphere, status="pending")
        SessionFactory.create(category=category, sphere=sphere, status="pending")
        SessionFactory.create(category=other_category, sphere=sphere, status="pending")

        response = authenticated_client.get(self.get_url(event, category))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/cfp-edit.html",
            context_data={
                "current_event": EventDTO.model_validate(event),
                "events": [EventDTO.model_validate(event)],
                "is_proposal_active": False,
                "stats": {
                    "hosts_count": 1 + 1 + 1,  # 3 unique presenters
                    "pending_proposals": 1 + 1 + 1,  # 3 pending sessions total
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 1 + 1 + 1,
                    "total_sessions": 1 + 1 + 1,  # pending + scheduled
                },
                "active_nav": "cfp",
                "category": ProposalCategoryDTO.model_validate(category),
                "form": ANY,
                "available_fields": [],
                "field_requirements": {},
                "field_order": [],
                "available_session_fields": [],
                "session_field_requirements": {},
                "session_field_order": [],
                "available_time_slots": [],
                "time_slot_requirements": {},
                "time_slot_order": [],
                "durations": [],
                "proposal_count": 1 + 1,  # Only 2 in this category
            },
        )

    # Data preservation tests

    def test_post_removing_field_requirement_preserves_existing_personal_data(
        self, authenticated_client, active_user, sphere, event
    ):
        """When a field requirement is removed, existing host data should be kept."""
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        email_field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", field_type="text"
        )
        # Setup: field is required and a host has filled in data
        PersonalDataFieldRequirement.objects.create(
            category=category, field=email_field, is_required=True
        )
        host = UserFactory.create()
        HostPersonalData.objects.create(
            user=host, event=event, field=email_field, value="host@example.com"
        )
        SessionFactory.create(category=category, presenter=host, sphere=event.sphere)

        # Action: remove the field requirement (don't include it in POST)
        authenticated_client.post(
            self.get_url(event, category),
            data={"name": "RPG Sessions"},  # No field_* entries
        )

        # Assert: requirement is gone but data is preserved
        assert not PersonalDataFieldRequirement.objects.filter(
            category=category, field=email_field
        ).exists()
        assert HostPersonalData.objects.filter(
            user=host, event=event, field=email_field, value="host@example.com"
        ).exists()

    def test_post_adding_field_requirement_does_not_create_data_for_existing_proposals(
        self, authenticated_client, active_user, sphere, event
    ):
        """Adding field requirement doesn't create data for existing proposals."""
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        email_field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", field_type="text"
        )
        # Setup: existing proposal without the field requirement
        host = UserFactory.create()
        SessionFactory.create(category=category, presenter=host, sphere=event.sphere)
        assert not HostPersonalData.objects.filter(
            user=host, event=event, field=email_field
        ).exists()

        # Action: add a new field requirement
        authenticated_client.post(
            self.get_url(event, category),
            data={
                "name": "RPG Sessions",
                f"field_{email_field.pk}": "required",
                "field_order": str(email_field.pk),
            },
        )

        # Assert: requirement exists but no data was auto-created for existing host
        assert PersonalDataFieldRequirement.objects.filter(
            category=category, field=email_field, is_required=True
        ).exists()
        assert not HostPersonalData.objects.filter(
            user=host, event=event, field=email_field
        ).exists()

    # Time slot requirement tests

    def test_get_includes_available_time_slots_in_context(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        day1 = datetime(2025, 6, 14, 10, 0, tzinfo=UTC)
        slot1 = TimeSlot.objects.create(
            event=event, start_time=day1, end_time=day1 + timedelta(hours=2)
        )
        slot2 = TimeSlot.objects.create(
            event=event,
            start_time=day1 + timedelta(hours=3),
            end_time=day1 + timedelta(hours=5),
        )

        response = authenticated_client.get(self.get_url(event, category))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/cfp-edit.html",
            context_data={
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
                "active_nav": "cfp",
                "category": ProposalCategoryDTO.model_validate(category),
                "form": ANY,
                "available_fields": [],
                "field_requirements": {},
                "field_order": [],
                "available_session_fields": [],
                "session_field_requirements": {},
                "session_field_order": [],
                "available_time_slots": [
                    TimeSlotDTO.model_validate(slot1),
                    TimeSlotDTO.model_validate(slot2),
                ],
                "time_slot_requirements": {},
                "time_slot_order": [],
                "durations": [],
                "proposal_count": 0,
            },
        )

    def test_get_includes_time_slot_requirements_in_context(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        day1 = datetime(2025, 6, 14, 10, 0, tzinfo=UTC)
        slot1 = TimeSlot.objects.create(
            event=event, start_time=day1, end_time=day1 + timedelta(hours=2)
        )
        slot2 = TimeSlot.objects.create(
            event=event,
            start_time=day1 + timedelta(hours=3),
            end_time=day1 + timedelta(hours=5),
        )
        TimeSlotRequirement.objects.create(
            category=category, time_slot=slot1, is_required=True
        )
        TimeSlotRequirement.objects.create(
            category=category, time_slot=slot2, is_required=True
        )

        response = authenticated_client.get(self.get_url(event, category))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/cfp-edit.html",
            context_data={
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
                "active_nav": "cfp",
                "category": ProposalCategoryDTO.model_validate(category),
                "form": ANY,
                "available_fields": [],
                "field_requirements": {},
                "field_order": [],
                "available_session_fields": [],
                "session_field_requirements": {},
                "session_field_order": [],
                "available_time_slots": [
                    TimeSlotDTO.model_validate(slot1),
                    TimeSlotDTO.model_validate(slot2),
                ],
                "time_slot_requirements": {slot1.pk: True, slot2.pk: True},
                "time_slot_order": [slot1.pk, slot2.pk],
                "durations": [],
                "proposal_count": 0,
            },
        )

    def test_get_returns_empty_time_slot_requirements_when_none_configured(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        day1 = datetime(2025, 6, 14, 10, 0, tzinfo=UTC)
        slot = TimeSlot.objects.create(
            event=event, start_time=day1, end_time=day1 + timedelta(hours=2)
        )

        response = authenticated_client.get(self.get_url(event, category))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/cfp-edit.html",
            context_data={
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
                "active_nav": "cfp",
                "category": ProposalCategoryDTO.model_validate(category),
                "form": ANY,
                "available_fields": [],
                "field_requirements": {},
                "field_order": [],
                "available_session_fields": [],
                "session_field_requirements": {},
                "session_field_order": [],
                "available_time_slots": [TimeSlotDTO.model_validate(slot)],
                "time_slot_requirements": {},
                "time_slot_order": [],
                "durations": [],
                "proposal_count": 0,
            },
        )

    def test_post_saves_time_slot_requirement_as_required(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        day1 = datetime(2025, 6, 14, 10, 0, tzinfo=UTC)
        slot = TimeSlot.objects.create(
            event=event, start_time=day1, end_time=day1 + timedelta(hours=2)
        )

        response = authenticated_client.post(
            self.get_url(event, category),
            data={"name": "RPG Sessions", f"time_slot_{slot.pk}": "required"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Session type updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/",
        )
        requirement = TimeSlotRequirement.objects.get(category=category, time_slot=slot)
        assert requirement.is_required is True

    def test_post_removes_time_slot_requirement_when_set_to_none(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        day1 = datetime(2025, 6, 14, 10, 0, tzinfo=UTC)
        slot = TimeSlot.objects.create(
            event=event, start_time=day1, end_time=day1 + timedelta(hours=2)
        )
        TimeSlotRequirement.objects.create(
            category=category, time_slot=slot, is_required=True
        )

        response = authenticated_client.post(
            self.get_url(event, category),
            data={"name": "RPG Sessions", f"time_slot_{slot.pk}": "none"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Session type updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/",
        )
        assert not TimeSlotRequirement.objects.filter(
            category=category, time_slot=slot
        ).exists()

    def test_post_saves_multiple_time_slot_requirements(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        day1 = datetime(2025, 6, 14, 10, 0, tzinfo=UTC)
        slot1 = TimeSlot.objects.create(
            event=event, start_time=day1, end_time=day1 + timedelta(hours=2)
        )
        slot2 = TimeSlot.objects.create(
            event=event,
            start_time=day1 + timedelta(hours=3),
            end_time=day1 + timedelta(hours=5),
        )
        slot3 = TimeSlot.objects.create(
            event=event,
            start_time=day1 + timedelta(hours=6),
            end_time=day1 + timedelta(hours=8),
        )

        response = authenticated_client.post(
            self.get_url(event, category),
            data={
                "name": "RPG Sessions",
                f"time_slot_{slot1.pk}": "required",
                f"time_slot_{slot2.pk}": "required",
                f"time_slot_{slot3.pk}": "none",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Session type updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/",
        )
        assert (
            TimeSlotRequirement.objects.filter(category=category).count()
            == 1 + 1  # slot1 + slot2 (slot3 is "none")
        )
        slot1_req = TimeSlotRequirement.objects.get(category=category, time_slot=slot1)
        slot2_req = TimeSlotRequirement.objects.get(category=category, time_slot=slot2)
        assert slot1_req.is_required is True
        assert slot2_req.is_required is True
        assert not TimeSlotRequirement.objects.filter(
            category=category, time_slot=slot3
        ).exists()

    def test_post_saves_time_slot_order(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        day1 = datetime(2025, 6, 14, 10, 0, tzinfo=UTC)
        slot1 = TimeSlot.objects.create(
            event=event, start_time=day1, end_time=day1 + timedelta(hours=2)
        )
        slot2 = TimeSlot.objects.create(
            event=event,
            start_time=day1 + timedelta(hours=3),
            end_time=day1 + timedelta(hours=5),
        )

        response = authenticated_client.post(
            self.get_url(event, category),
            data={
                "name": "RPG Sessions",
                f"time_slot_{slot1.pk}": "required",
                f"time_slot_{slot2.pk}": "required",
                "time_slot_order": f"{slot2.pk},{slot1.pk}",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Session type updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/",
        )
        slot1_req = TimeSlotRequirement.objects.get(category=category, time_slot=slot1)
        slot2_req = TimeSlotRequirement.objects.get(category=category, time_slot=slot2)
        assert slot2_req.order == 0
        assert slot1_req.order == 1

    def test_get_includes_time_slot_order_in_context(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )
        day1 = datetime(2025, 6, 14, 10, 0, tzinfo=UTC)
        slot1 = TimeSlot.objects.create(
            event=event, start_time=day1, end_time=day1 + timedelta(hours=2)
        )
        slot2 = TimeSlot.objects.create(
            event=event,
            start_time=day1 + timedelta(hours=3),
            end_time=day1 + timedelta(hours=5),
        )
        TimeSlotRequirement.objects.create(
            category=category, time_slot=slot1, is_required=True, order=1
        )
        TimeSlotRequirement.objects.create(
            category=category, time_slot=slot2, is_required=True, order=0
        )

        response = authenticated_client.get(self.get_url(event, category))

        # Order should be [slot2, slot1] based on order field
        # (slot2 has order=0, slot1 has order=1)
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/cfp-edit.html",
            context_data={
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
                "active_nav": "cfp",
                "category": ProposalCategoryDTO.model_validate(category),
                "form": ANY,
                "available_fields": [],
                "field_requirements": {},
                "field_order": [],
                "available_session_fields": [],
                "session_field_requirements": {},
                "session_field_order": [],
                "available_time_slots": [
                    TimeSlotDTO.model_validate(slot2),
                    TimeSlotDTO.model_validate(slot1),
                ],
                "time_slot_requirements": {slot1.pk: True, slot2.pk: True},
                "time_slot_order": [slot2.pk, slot1.pk],
                "durations": [],
                "proposal_count": 0,
            },
        )

    # Participant limits tests

    def test_post_saves_participant_limits(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )

        response = authenticated_client.post(
            self.get_url(event, category),
            data={
                "name": "RPG Sessions",
                "min_participants_limit": "3",
                "max_participants_limit": "10",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Session type updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/",
        )
        category.refresh_from_db()
        assert category.min_participants_limit == int("3")
        assert category.max_participants_limit == int("10")

    def test_post_saves_zero_limits(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event,
            name="RPG Sessions",
            slug="rpg-sessions",
            min_participants_limit=5,
            max_participants_limit=20,
        )

        response = authenticated_client.post(
            self.get_url(event, category),
            data={
                "name": "RPG Sessions",
                "min_participants_limit": "0",
                "max_participants_limit": "0",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Session type updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/",
        )
        category.refresh_from_db()
        assert category.min_participants_limit == 0
        assert category.max_participants_limit == 0

    def test_post_empty_limits_default_to_zero(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(
            event=event, name="RPG Sessions", slug="rpg-sessions"
        )

        response = authenticated_client.post(
            self.get_url(event, category), data={"name": "RPG Sessions"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Session type updated successfully.")],
            url=f"/panel/event/{event.slug}/cfp/",
        )
        category.refresh_from_db()
        assert category.min_participants_limit == 0
        assert category.max_participants_limit == 0
