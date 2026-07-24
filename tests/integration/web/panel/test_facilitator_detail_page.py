"""Integration tests for the facilitator detail page."""

from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import (
    Facilitator,
    PersonalDataField,
    PersonalDataFieldValue,
    ProposalCategory,
    Session,
)
from ludamus.pacts import (
    EventDTO,
    FacilitatorDTO,
    PersonalDataFieldDTO,
    SessionListItemDTO,
    SessionStatus,
)
from ludamus.pacts.crowd import UserDTO
from tests.integration.conftest import UserFactory
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


def _make_facilitator(event, **kwargs):
    defaults = {"display_name": "Alice", "slug": "alice", "user": None}
    defaults.update(kwargs)
    return Facilitator.objects.create(event=event, **defaults)


def _make_personal_data_field(event, **kwargs):
    defaults = {
        "name": "Dietary requirements",
        "question": "Any dietary requirements?",
        "slug": "dietary",
        "field_type": "text",
        "order": 0,
    }
    defaults.update(kwargs)
    return PersonalDataField.objects.create(event=event, **defaults)


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


def _detail_tabs(event, facilitator_slug):
    return {
        "active_tab": "details",
        "tab_urls": {
            "details": reverse(
                "panel:facilitator-detail",
                kwargs={"slug": event.slug, "facilitator_slug": facilitator_slug},
            ),
            "history": reverse(
                "panel:facilitator-history",
                kwargs={"slug": event.slug, "facilitator_slug": facilitator_slug},
            ),
        },
    }


class TestFacilitatorDetailPageView:
    """Tests for /panel/event/<slug>/facilitators/<facilitator_slug>/ page."""

    @staticmethod
    def get_url(event, facilitator_slug="alice"):
        return reverse(
            "panel:facilitator-detail",
            kwargs={"slug": event.slug, "facilitator_slug": facilitator_slug},
        )

    def test_get_exposes_internal_comment(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        facilitator = _make_facilitator(
            event, internal_comment="Possible duplicate of Bob"
        )

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-detail.html",
            context_data={
                **_base_context(event),
                **_detail_tabs(event, facilitator.slug),
                "facilitator": FacilitatorDTO.model_validate(facilitator),
                "linked_user": None,
                "accreditation_type_display": "None",
                "personal_data_items": [],
                "has_personal_data": False,
                "sessions": [],
            },
            contains="Possible duplicate of Bob",
        )

    def test_get_renders_sessions_linking_to_proposal_detail(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        facilitator = _make_facilitator(event)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        session = Session.objects.create(
            event=event,
            category=category,
            display_name="Host",
            title="Attached Session",
            slug="attached-session",
            participants_limit=4,
            status="pending",
        )
        session.facilitators.add(facilitator)
        proposal_url = reverse(
            "panel:proposal-detail",
            kwargs={"slug": event.slug, "proposal_id": session.pk},
        )

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-detail.html",
            context_data={
                **_base_context(event),
                **_detail_tabs(event, facilitator.slug),
                "stats": {
                    "hosts_count": 0,
                    "pending_proposals": 1,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 1,
                    "total_sessions": 1,
                },
                "facilitator": FacilitatorDTO.model_validate(facilitator),
                "linked_user": None,
                "accreditation_type_display": "None",
                "personal_data_items": [],
                "has_personal_data": False,
                "sessions": [
                    SessionListItemDTO(
                        category_name="RPG",
                        creation_time=session.creation_time,
                        display_name="Host",
                        is_scheduled=False,
                        pk=session.pk,
                        status=SessionStatus.PENDING,
                        title="Attached Session",
                    )
                ],
            },
            contains=[f'href="{proposal_url}"', "Attached Session"],
        )

    def test_get_shows_linked_user_name_and_email(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        linked = UserFactory(name="Bob Builder", email="bob@example.com")
        facilitator = _make_facilitator(event, user=linked)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-detail.html",
            context_data={
                **_base_context(event),
                **_detail_tabs(event, facilitator.slug),
                "facilitator": FacilitatorDTO.model_validate(facilitator),
                "linked_user": UserDTO.model_validate(linked),
                "accreditation_type_display": "None",
                "personal_data_items": [],
                "has_personal_data": False,
                "sessions": [],
            },
            contains=["Bob Builder", "bob@example.com"],
        )

    def test_get_shows_no_linked_user_when_user_is_not_active(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        connected = UserFactory(name="Ghost", user_type="connected")
        facilitator = _make_facilitator(event, user=connected)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-detail.html",
            context_data={
                **_base_context(event),
                **_detail_tabs(event, facilitator.slug),
                "facilitator": FacilitatorDTO.model_validate(facilitator),
                "linked_user": None,
                "accreditation_type_display": "None",
                "personal_data_items": [],
                "has_personal_data": False,
                "sessions": [],
            },
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
            "panel:facilitator-detail",
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

    def test_get_ok_with_no_personal_data_fields(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        facilitator = _make_facilitator(event)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-detail.html",
            context_data={
                **_base_context(event),
                **_detail_tabs(event, facilitator.slug),
                "facilitator": FacilitatorDTO.model_validate(facilitator),
                "linked_user": None,
                "accreditation_type_display": "None",
                "personal_data_items": [],
                "has_personal_data": False,
                "sessions": [],
            },
        )

    def test_get_shows_accreditation_type(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        _make_facilitator(event, accreditation_type="honorary")

        response = authenticated_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        html = response.content.decode()
        assert "Accreditation type" in html
        assert "Honorary" in html

    def test_get_shows_personal_data_fields(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        facilitator = _make_facilitator(event)
        field = _make_personal_data_field(event)

        response = authenticated_client.get(self.get_url(event))

        field_dto = PersonalDataFieldDTO(
            pk=field.pk,
            name=field.name,
            question=field.question,
            slug=field.slug,
            field_type=field.field_type,
            order=field.order,
            options=[],
        )
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-detail.html",
            context_data={
                **_base_context(event),
                **_detail_tabs(event, facilitator.slug),
                "facilitator": FacilitatorDTO.model_validate(facilitator),
                "linked_user": None,
                "accreditation_type_display": "None",
                "personal_data_items": [(field_dto, None)],
                "has_personal_data": False,
                "sessions": [],
            },
        )

    def test_get_renders_personal_data_values(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        facilitator = _make_facilitator(event)
        values = [
            ("Consent", "consent", "checkbox", True),
            ("Declined", "declined", "checkbox", False),
            ("Nickname", "nickname", "text", "Bob"),
            ("Empty", "empty", "text", ""),
        ]
        for order, (name, slug, field_type, value) in enumerate(values):
            field = _make_personal_data_field(
                event,
                name=name,
                question=name,
                slug=slug,
                field_type=field_type,
                order=order,
            )
            PersonalDataFieldValue.objects.create(
                facilitator=facilitator, event=event, field=field, value=value
            )

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-detail.html",
            context_data=ANY,
            contains=["Consent", "Yes", "Declined", "Nickname", "Bob", "Empty"],
        )
