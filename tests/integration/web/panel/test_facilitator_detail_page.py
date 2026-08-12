"""Integration tests for the facilitator detail page."""

from datetime import UTC, datetime
from http import HTTPStatus
from unittest.mock import ANY

from django.urls import reverse

from ludamus.links.db.django.models import (
    PersonalDataField,
    PersonalDataFieldValue,
    ProposalCategory,
    Session,
)
from ludamus.pacts import (
    FacilitatorDTO,
    OrganizerFieldDTO,
    SessionListItemDTO,
    SessionStatus,
)
from ludamus.pacts.crowd import UserDTO
from tests.integration.conftest import UserFactory
from tests.integration.utils import assert_login_required, assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_facilitator_not_found,
    assert_not_a_manager,
    make_facilitator,
    panel_context,
)

_DELETED_AT = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)


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

    def test_get_exposes_internal_comment(self, panel_client, event):
        facilitator = make_facilitator(
            event, internal_comment="Possible duplicate of Bob"
        )

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-detail.html",
            context_data={
                **panel_context(event, active_nav="facilitators"),
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

    def test_get_renders_a_deleted_facilitator(self, panel_client, event):
        facilitator = make_facilitator(event, deleted_at=_DELETED_AT)

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-detail.html",
            context_data={
                **panel_context(event, active_nav="facilitators"),
                **_detail_tabs(event, facilitator.slug),
                "facilitator": FacilitatorDTO.model_validate(facilitator),
                "linked_user": None,
                "accreditation_type_display": "None",
                "personal_data_items": [],
                "has_personal_data": False,
                "sessions": [],
            },
        )

    def test_get_renders_sessions_linking_to_proposal_detail(self, panel_client, event):
        facilitator = make_facilitator(event)
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

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-detail.html",
            context_data={
                **panel_context(event, active_nav="facilitators"),
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

    def test_get_lists_the_deleted_sessions_that_block_a_deletion(
        self, panel_client, event
    ):
        # The refusal says "deleted ones included", so the page has to show
        # which ones — otherwise nothing in the facilitator UI names them.
        facilitator = make_facilitator(event)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        session = Session.objects.create(
            event=event,
            category=category,
            display_name="Host",
            title="Dead Session",
            slug="dead-session",
            participants_limit=4,
            status="pending",
            deleted_at=_DELETED_AT,
        )
        session.facilitators.add(facilitator)

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-detail.html",
            context_data={
                **panel_context(event, active_nav="facilitators"),
                **_detail_tabs(event, facilitator.slug),
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
                        is_deleted=True,
                        is_scheduled=False,
                        pk=session.pk,
                        status=SessionStatus.PENDING,
                        title="Dead Session",
                    )
                ],
            },
        )

    def test_get_shows_linked_user_name_and_email(self, panel_client, event):
        linked = UserFactory(name="Bob Builder", email="bob@example.com")
        facilitator = make_facilitator(event, user=linked)

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-detail.html",
            context_data={
                **panel_context(event, active_nav="facilitators"),
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

    def test_get_shows_the_organizer(self, panel_client, event):
        organizer = UserFactory(name="Olga Organizer", email="olga@example.com")
        facilitator = make_facilitator(event, organizer=organizer)

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-detail.html",
            context_data={
                **panel_context(event, active_nav="facilitators"),
                **_detail_tabs(event, facilitator.slug),
                "facilitator": (
                    FacilitatorDTO.model_validate(facilitator).model_copy(
                        update={"organizer_name": "Olga Organizer"}
                    )
                ),
                "linked_user": None,
                "accreditation_type_display": "None",
                "personal_data_items": [],
                "has_personal_data": False,
                "sessions": [],
            },
        )

    def test_get_shows_no_linked_user_when_user_is_not_active(
        self, panel_client, event
    ):
        connected = UserFactory(name="Ghost", user_type="connected")
        facilitator = make_facilitator(event, user=connected)

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-detail.html",
            context_data={
                **panel_context(event, active_nav="facilitators"),
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

        assert_login_required(response, url)

    def test_get_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event))

        assert_not_a_manager(response)

    def test_get_redirects_when_event_not_found(self, panel_client):
        url = reverse(
            "panel:facilitator-detail",
            kwargs={"slug": "nonexistent", "facilitator_slug": "alice"},
        )

        response = panel_client.get(url)

        assert_event_not_found(response)

    def test_get_redirects_when_facilitator_not_found(self, panel_client, event):
        response = panel_client.get(self.get_url(event, "nonexistent"))

        assert_facilitator_not_found(response, event)

    def test_get_ok_with_no_personal_data_fields(self, panel_client, event):
        facilitator = make_facilitator(event)

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-detail.html",
            context_data={
                **panel_context(event, active_nav="facilitators"),
                **_detail_tabs(event, facilitator.slug),
                "facilitator": FacilitatorDTO.model_validate(facilitator),
                "linked_user": None,
                "accreditation_type_display": "None",
                "personal_data_items": [],
                "has_personal_data": False,
                "sessions": [],
            },
        )

    def test_get_shows_accreditation_type(self, panel_client, event):
        facilitator = make_facilitator(event, accreditation_type="honorary")

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-detail.html",
            context_data={
                **panel_context(event, active_nav="facilitators"),
                **_detail_tabs(event, facilitator.slug),
                "facilitator": FacilitatorDTO.model_validate(facilitator),
                "linked_user": None,
                "accreditation_type_display": "Honorary",
                "personal_data_items": [],
                "has_personal_data": False,
                "sessions": [],
            },
        )

    def test_get_shows_personal_data_fields(self, panel_client, event):
        facilitator = make_facilitator(event)
        field = _make_personal_data_field(event)

        response = panel_client.get(self.get_url(event))

        field_dto = OrganizerFieldDTO(
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
                **panel_context(event, active_nav="facilitators"),
                **_detail_tabs(event, facilitator.slug),
                "facilitator": FacilitatorDTO.model_validate(facilitator),
                "linked_user": None,
                "accreditation_type_display": "None",
                "personal_data_items": [(field_dto, None)],
                "has_personal_data": False,
                "sessions": [],
            },
        )

    def test_get_renders_personal_data_values(self, panel_client, event):
        facilitator = make_facilitator(event)
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

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-detail.html",
            context_data=ANY,
            contains=["Consent", "Yes", "Declined", "Nickname", "Bob", "Empty"],
        )
