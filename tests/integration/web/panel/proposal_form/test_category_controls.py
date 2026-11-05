"""Fields component, durations and limits the category drives."""

from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import Facilitator, ProposalCategory, Session
from ludamus.pacts import ProposalCategoryDTO
from ludamus.pacts.durations import MAX_DURATION_HOURS, MAX_DURATION_MINUTES
from tests.integration.conftest import EventFactory
from tests.integration.utils import assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_proposal_not_found,
    facilitator_list_item_dto,
)
from tests.integration.web.panel.proposal_form.helpers import (
    category_with_field,
    form_context,
    form_fields_url,
    form_page,
    form_url,
    make_session,
)

CUSTOM_DURATION_MINUTES = 45
CATEGORY_MAX_PARTICIPANTS = 9
CATEGORY_MIN_PARTICIPANTS = 4
LIMIT_ABOVE_CATEGORY_MAX = 500
LIMIT_BELOW_CATEGORY_MIN = 1
DEFAULT_SESSION_PARTICIPANTS = 5
MISSING_EVENT_FIELDS_ROUTES = (
    pytest.param("panel:proposal-create-fields", {"slug": "nonexistent"}, id="create"),
    pytest.param(
        "panel:proposal-edit-fields",
        {"slug": "nonexistent", "proposal_id": 1},
        id="edit",
    ),
)


class TestBothModes:
    def test_get_fields_component_follows_the_requested_category(
        self, panel_client, event, form_mode
    ):
        category_with_field(event, name="A", slug="a", field_slug="only-a")
        category_b, _field = category_with_field(
            event, name="B", slug="b", field_slug="only-b"
        )

        response = panel_client.get(
            form_mode.fields_url, data={"category_id": category_b.pk}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/parts/proposal-session-fields.html",
            # field_descriptors carry BoundFields, which don't compare usefully.
            # No events, stats or active_nav: a category swap re-renders one
            # fieldset and builds none of the page chrome.
            context_data={
                "field_descriptors": ANY,
                "form": ANY,
                "category": ProposalCategoryDTO.model_validate(category_b),
                "orphan_values": [],
                "fields_url": form_mode.fields_url,
            },
            contains='name="session_only-b"',
            not_contains='name="session_only-a"',
        )

    @pytest.mark.parametrize(("route", "kwargs"), MISSING_EVENT_FIELDS_ROUTES)
    def test_get_fields_component_redirects_when_event_not_found(
        self, panel_client, route, kwargs
    ):
        response = panel_client.get(reverse(route, kwargs=kwargs))

        assert_event_not_found(response)


class TestCreate:
    def test_post_to_fields_component_is_rejected(self, panel_client, event):
        category, _field = category_with_field(
            event, name="A", slug="a", field_slug="only-a"
        )

        response = panel_client.post(
            form_fields_url(event), data={"category_id": category.pk}
        )

        # The fragment endpoint is read-only; it must not share the page view's
        # create handler.
        assert_response(response, HTTPStatus.METHOD_NOT_ALLOWED)
        assert not Session.objects.exists()

    def test_get_fields_component_follows_the_category_derived_controls(
        self, panel_client, event
    ):
        ProposalCategory.objects.create(
            event=event, name="A", slug="a", durations=["PT1H"]
        )
        category_b = ProposalCategory.objects.create(
            event=event, name="B", slug="b", durations=["PT3H"]
        )

        response = panel_client.get(
            form_fields_url(event), data={"category_id": category_b.pk}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/parts/proposal-session-fields.html",
            context_data={
                "category": ProposalCategoryDTO.model_validate(category_b),
                "field_descriptors": [],
                "form": ANY,
                "orphan_values": [],
                "fields_url": form_fields_url(event),
            },
        )
        form = response.context["form"]
        assert form.fields["duration"].choices == [
            ("", "---"),
            ("PT3H", "3h"),
            ("custom", "Custom"),
        ]

    def test_get_fields_component_renders_empty_when_event_has_no_categories(
        self, panel_client, event
    ):
        response = panel_client.get(form_fields_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/parts/proposal-session-fields.html",
            context_data={
                "field_descriptors": [],
                "form": ANY,
                "category": None,
                "orphan_values": [],
                "fields_url": form_fields_url(event),
            },
        )

    def test_get_offers_the_categorys_durations_as_choices(self, panel_client, event):
        ProposalCategory.objects.create(
            event=event, name="RPG", slug="rpg", durations=["PT1H", "PT2H"]
        )

        response = panel_client.get(form_url(event))

        duration = response.context["form"].fields["duration"]
        assert duration.choices == [
            ("", "---"),
            ("PT1H", "1h"),
            ("PT2H", "2h"),
            ("custom", "Custom"),
        ]
        assert 'value="PT1H"' in response.content.decode()

    def test_get_drops_the_duration_picker_without_configured_durations(
        self, panel_client, event
    ):
        ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")

        response = panel_client.get(form_url(event))

        # No presets to pick from, so the hour/minute steppers are the whole
        # control — no picker, and no free-text ISO field either.
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={**form_context(event)},
        )
        fields = response.context["form"].fields
        assert "duration" not in fields
        assert fields["duration_hours"].max_value == MAX_DURATION_HOURS
        assert fields["duration_minutes"].max_value == MAX_DURATION_MINUTES

    def test_post_stores_a_preset_duration(self, panel_client, event):
        category = ProposalCategory.objects.create(
            event=event, name="RPG", slug="rpg", durations=["PT1H", "PT2H"]
        )
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )

        response = panel_client.post(
            form_url(event),
            data={
                "facilitators_submitted": "1",
                "facilitator_ids": [facilitator.pk],
                "category_id": category.pk,
                "title": "Preset",
                "facilitator_name": "Test Host",
                "duration": "PT2H",
            },
        )

        new_session = Session.objects.get(title="Preset")
        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal created successfully.")],
            url=reverse(
                "panel:proposal-detail",
                kwargs={"slug": event.slug, "proposal_id": new_session.pk},
            ),
        )
        assert new_session.duration == "PT2H"

    def test_post_stores_a_custom_duration(self, panel_client, event):
        category = ProposalCategory.objects.create(
            event=event, name="RPG", slug="rpg", durations=["PT1H"]
        )
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )

        response = panel_client.post(
            form_url(event),
            data={
                "facilitators_submitted": "1",
                "facilitator_ids": [facilitator.pk],
                "category_id": category.pk,
                "title": "Custom",
                "facilitator_name": "Test Host",
                "duration": "custom",
                "duration_hours": 1,
                "duration_minutes": 45,
            },
        )

        new_session = Session.objects.get(title="Custom")
        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal created successfully.")],
            url=reverse(
                "panel:proposal-detail",
                kwargs={"slug": event.slug, "proposal_id": new_session.pk},
            ),
        )
        assert new_session.duration == "PT1H45M"

    def test_post_stores_steppers_when_the_category_has_no_durations(
        self, panel_client, event
    ):
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )

        response = panel_client.post(
            form_url(event),
            data={
                "facilitators_submitted": "1",
                "facilitator_ids": [facilitator.pk],
                "category_id": category.pk,
                "title": "Steppers",
                "facilitator_name": "Test Host",
                "duration_minutes": 45,
            },
        )

        new_session = Session.objects.get(title="Steppers")
        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal created successfully.")],
            url=reverse(
                "panel:proposal-detail",
                kwargs={"slug": event.slug, "proposal_id": new_session.pk},
            ),
        )
        assert new_session.duration == "PT45M"

    def test_post_rejects_a_custom_duration_left_empty(self, panel_client, event):
        category = ProposalCategory.objects.create(
            event=event, name="RPG", slug="rpg", durations=["PT1H"]
        )
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )

        response = panel_client.post(
            form_url(event),
            data={
                "facilitators_submitted": "1",
                "facilitator_ids": [facilitator.pk],
                "category_id": category.pk,
                "title": "Empty Custom",
                "facilitator_name": "Test Host",
                "duration": "custom",
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={
                **form_context(event),
                "all_facilitators": [facilitator_list_item_dto(facilitator)],
                "assigned_facilitator_pks": {facilitator.pk},
            },
        )
        form = response.context["form"]
        assert form.errors["duration"] == ["Enter how long the session lasts."]

    def test_post_rejects_out_of_range_steppers(self, panel_client, event):
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )

        response = panel_client.post(
            form_url(event),
            data={
                "facilitators_submitted": "1",
                "facilitator_ids": [facilitator.pk],
                "category_id": category.pk,
                "title": "Too Long",
                "facilitator_name": "Test Host",
                "duration_hours": 99,
                "duration_minutes": 99,
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={
                **form_context(event),
                "all_facilitators": [facilitator_list_item_dto(facilitator)],
                "assigned_facilitator_pks": {facilitator.pk},
            },
        )
        form = response.context["form"]
        assert form.errors["duration_hours"] == [
            f"Ensure this value is less than or equal to {MAX_DURATION_HOURS}."
        ]
        assert form.errors["duration_minutes"] == [
            f"Ensure this value is less than or equal to {MAX_DURATION_MINUTES}."
        ]
        assert not Session.objects.filter(title="Empty Custom").exists()


class TestEdit:
    def test_get_preselects_a_stored_preset_duration(self, panel_client, event):
        session = make_session(event, duration="PT1H")
        session.category.durations = ["PT1H", "PT2H"]
        session.category.save()

        response = panel_client.get(form_url(event, session.pk))

        assert_response(response, HTTPStatus.OK, **form_page(event, session))
        form = response.context["form"]
        assert form.initial["duration"] == "PT1H"

    def test_get_preselects_custom_for_a_duration_outside_the_presets(
        self, panel_client, event
    ):
        session = make_session(event, duration="PT1H45M")
        session.category.durations = ["PT1H"]
        session.category.save()

        response = panel_client.get(form_url(event, session.pk))

        assert_response(response, HTTPStatus.OK, **form_page(event, session))
        initial = response.context["form"].initial
        assert initial["duration"] == "custom"
        assert initial["duration_hours"] == 1
        assert initial["duration_minutes"] == CUSTOM_DURATION_MINUTES

    def test_post_accepts_a_limit_above_the_category_maximum(self, panel_client, event):
        # The category's bounds guard the submission wizard, not the organizer
        # reviewing the proposal here.
        bounded = ProposalCategory.objects.create(
            event=event,
            name="Lectures",
            slug="lectures",
            min_participants_limit=CATEGORY_MIN_PARTICIPANTS,
            max_participants_limit=CATEGORY_MAX_PARTICIPANTS,
        )
        session = make_session(event, category=bounded)

        response = panel_client.post(
            form_url(event, session.pk),
            data={
                "category_id": bounded.pk,
                "title": "Updated",
                "facilitator_name": "Host",
                "description": "d",
                "contact_email": "",
                "participants_limit": LIMIT_ABOVE_CATEGORY_MAX,
                "min_age": 0,
                "duration_hours": 2,
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
        assert session.participants_limit == LIMIT_ABOVE_CATEGORY_MAX

    def test_post_accepts_a_limit_below_the_category_minimum(self, panel_client, event):
        # A session already smaller than its category's floor stays editable:
        # the floor never applies on this form.
        bounded = ProposalCategory.objects.create(
            event=event,
            name="Lectures",
            slug="lectures",
            min_participants_limit=CATEGORY_MIN_PARTICIPANTS,
        )
        session = make_session(
            event, category=bounded, participants_limit=DEFAULT_SESSION_PARTICIPANTS
        )

        response = panel_client.post(
            form_url(event, session.pk),
            data={
                "category_id": bounded.pk,
                "title": "Updated",
                "facilitator_name": "Host",
                "description": "d",
                "contact_email": "",
                "participants_limit": LIMIT_BELOW_CATEGORY_MIN,
                "min_age": 0,
                "duration_hours": 2,
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
        assert session.participants_limit == LIMIT_BELOW_CATEGORY_MIN

    def test_get_fields_component_redirects_when_proposal_not_found(
        self, panel_client, event
    ):
        response = panel_client.get(form_fields_url(event, 99999))

        assert_proposal_not_found(response, event)

    def test_get_fields_component_redirects_for_a_proposal_of_another_event(
        self, panel_client, sphere, event
    ):
        other_event = EventFactory(sphere=sphere)
        session = make_session(other_event)

        response = panel_client.get(form_fields_url(event, session.pk))

        assert_proposal_not_found(response, event)
