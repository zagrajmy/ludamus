"""Integration tests for /panel/event/<slug>/facilitators/ page."""

from http import HTTPStatus

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import (
    AccreditationType,
    EventPanelSettings,
    Facilitator,
    FacilitatorChangeLog,
    PersonalDataField,
    PersonalDataFieldValue,
)
from ludamus.pacts import EventDTO, FacilitatorListItemDTO, PersonalDataFieldDTO
from tests.integration.conftest import EventFactory
from tests.integration.utils import PageMatcher, assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."

_PAGE_SIZE = 50
_SEED_COUNT = 60
_LAST_PAGE_COUNT = _SEED_COUNT - _PAGE_SIZE
_TOTAL_PAGES = 2


def _event_context(event):
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


def _field_dto(field):
    return PersonalDataFieldDTO(
        field_type=field.field_type,
        is_multiple=field.is_multiple,
        name=field.name,
        options=[],
        order=field.order,
        pk=field.pk,
        question=field.question,
        slug=field.slug,
    )


def _base_context(event):
    return {
        **_event_context(event),
        "filter_search": "",
        "filter_accreditation": None,
        "filter_flagged": False,
        "filter_sort": "name",
        "filters_active": False,
        "accreditation_types": [(t.value, t.label) for t in AccreditationType],
        "accreditation_labels": {t.value: t.label for t in AccreditationType},
        "displayed_fields": [],
        "column_values": {},
        "filterable_fields": [],
        "filter_fields": {},
    }


class TestFacilitatorsPageView:
    """Tests for /panel/event/<slug>/facilitators/ page."""

    @staticmethod
    def get_url(event):
        return reverse("panel:facilitators", kwargs={"slug": event.slug})

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
        url = reverse("panel:facilitators", kwargs={"slug": "nonexistent"})

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url=reverse("panel:index"),
        )

    def test_get_ok_for_sphere_manager(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitators.html",
            context_data={
                **_base_context(event),
                "facilitators": [],
                "page_obj": PageMatcher(number=1, num_pages=1),
            },
        )

    def test_get_lists_facilitators_for_event(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitators.html",
            context_data={
                **_base_context(event),
                "facilitators": [
                    FacilitatorListItemDTO(
                        accreditation_type="none",
                        display_name="Alice",
                        pk=response.context["facilitators"][0].pk,
                        slug="alice",
                        user_id=None,
                        session_count=0,
                    )
                ],
                "page_obj": PageMatcher(number=1, num_pages=1),
            },
        )

    def test_search_filters_by_display_name(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )
        Facilitator.objects.create(
            event=event, display_name="Bob", slug="bob", user=None
        )

        response = authenticated_client.get(self.get_url(event), {"search": "Alic"})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitators.html",
            context_data={
                **_base_context(event),
                "facilitators": [
                    FacilitatorListItemDTO(
                        accreditation_type="none",
                        display_name="Alice",
                        pk=response.context["facilitators"][0].pk,
                        slug="alice",
                        user_id=None,
                        session_count=0,
                    )
                ],
                "page_obj": PageMatcher(number=1, num_pages=1),
                "filter_search": "Alic",
                "filters_active": True,
            },
        )

    def test_search_matches_text_personal_data(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        field = PersonalDataField.objects.create(
            event=event,
            name="Email",
            question="Email?",
            slug="email",
            field_type="text",
            order=0,
        )
        alice = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )
        PersonalDataFieldValue.objects.create(
            facilitator=alice, event=event, field=field, value="alice@example.com"
        )
        Facilitator.objects.create(
            event=event, display_name="Bob", slug="bob", user=None
        )

        response = authenticated_client.get(
            self.get_url(event), {"search": "alice@example"}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitators.html",
            context_data={
                **_base_context(event),
                "facilitators": [
                    FacilitatorListItemDTO(
                        accreditation_type="none",
                        display_name="Alice",
                        pk=response.context["facilitators"][0].pk,
                        slug="alice",
                        user_id=None,
                        session_count=0,
                    )
                ],
                "page_obj": PageMatcher(number=1, num_pages=1),
                "filter_search": "alice@example",
                "filters_active": True,
            },
        )

    def test_search_ignores_select_personal_data(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        field = PersonalDataField.objects.create(
            event=event,
            name="Team",
            question="Team?",
            slug="team",
            field_type="select",
            order=0,
        )
        alice = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )
        PersonalDataFieldValue.objects.create(
            facilitator=alice, event=event, field=field, value="Reds"
        )

        response = authenticated_client.get(self.get_url(event), {"search": "Reds"})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitators.html",
            context_data={
                **_base_context(event),
                "facilitators": [],
                "page_obj": PageMatcher(number=1, num_pages=1),
                "filter_search": "Reds",
                "filters_active": True,
                "filterable_fields": [_field_dto(field)],
                "filter_fields": {field.pk: ""},
            },
        )

    def test_accreditation_filter(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        Facilitator.objects.create(
            event=event,
            display_name="Guest",
            slug="guest",
            user=None,
            accreditation_type=AccreditationType.GUEST,
        )
        Facilitator.objects.create(
            event=event, display_name="Plain", slug="plain", user=None
        )

        response = authenticated_client.get(
            self.get_url(event), {"accreditation": "guest"}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitators.html",
            context_data={
                **_base_context(event),
                "facilitators": [
                    FacilitatorListItemDTO(
                        accreditation_type="guest",
                        display_name="Guest",
                        pk=response.context["facilitators"][0].pk,
                        slug="guest",
                        user_id=None,
                        session_count=0,
                    )
                ],
                "page_obj": PageMatcher(number=1, num_pages=1),
                "filter_accreditation": "guest",
                "filters_active": True,
            },
        )

    def test_sort_by_name_descending(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        for name in ("Alice", "Bob", "Carol"):
            Facilitator.objects.create(
                event=event, display_name=name, slug=name.lower(), user=None
            )

        response = authenticated_client.get(self.get_url(event), {"sort": "-name"})

        listed = response.context["facilitators"]
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitators.html",
            context_data={
                **_base_context(event),
                "facilitators": [
                    FacilitatorListItemDTO(
                        accreditation_type="none",
                        display_name=name,
                        pk=listed[index].pk,
                        slug=name.lower(),
                        user_id=None,
                        session_count=0,
                    )
                    for index, name in enumerate(("Carol", "Bob", "Alice"))
                ],
                "page_obj": PageMatcher(number=1, num_pages=1),
                "filter_sort": "-name",
            },
        )

    def test_flagged_filter(self, authenticated_client, active_user, sphere, event):
        sphere.managers.add(active_user)
        Facilitator.objects.create(
            event=event,
            display_name="Flagged",
            slug="flagged",
            user=None,
            flagged_for_deletion=True,
        )
        Facilitator.objects.create(
            event=event, display_name="Normal", slug="normal", user=None
        )

        response = authenticated_client.get(self.get_url(event), {"flagged": "true"})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitators.html",
            context_data={
                **_base_context(event),
                "facilitators": [
                    FacilitatorListItemDTO(
                        accreditation_type="none",
                        display_name="Flagged",
                        flagged_for_deletion=True,
                        pk=response.context["facilitators"][0].pk,
                        slug="flagged",
                        user_id=None,
                        session_count=0,
                    )
                ],
                "page_obj": PageMatcher(number=1, num_pages=1),
                "filter_flagged": True,
                "filters_active": True,
            },
        )

    def test_displayed_columns_show_field_values(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        field = PersonalDataField.objects.create(
            event=event,
            name="Email",
            question="Email?",
            slug="email",
            field_type="text",
            order=0,
        )
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )
        PersonalDataFieldValue.objects.create(
            facilitator=facilitator, event=event, field=field, value="alice@example.com"
        )
        panel_settings = EventPanelSettings.objects.create(event=event)
        panel_settings.displayed_facilitator_fields.add(field)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitators.html",
            context_data={
                **_base_context(event),
                "facilitators": [
                    FacilitatorListItemDTO(
                        accreditation_type="none",
                        display_name="Alice",
                        pk=facilitator.pk,
                        slug="alice",
                        user_id=None,
                        session_count=0,
                    )
                ],
                "page_obj": PageMatcher(number=1, num_pages=1),
                "displayed_fields": [_field_dto(field)],
                "column_values": {facilitator.pk: {"email": "alice@example.com"}},
            },
        )

    def test_displayed_columns_format_bool_and_list(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        checkbox_field = PersonalDataField.objects.create(
            event=event,
            name="Vegan",
            question="Vegan?",
            slug="vegan",
            field_type="checkbox",
            order=0,
        )
        multi_field = PersonalDataField.objects.create(
            event=event,
            name="Teams",
            question="Teams?",
            slug="teams",
            field_type="select",
            is_multiple=True,
            order=1,
        )
        yes = Facilitator.objects.create(
            event=event, display_name="Yes", slug="yes", user=None
        )
        no = Facilitator.objects.create(
            event=event, display_name="No", slug="no", user=None
        )
        PersonalDataFieldValue.objects.create(
            facilitator=yes, event=event, field=checkbox_field, value=True
        )
        PersonalDataFieldValue.objects.create(
            facilitator=no, event=event, field=checkbox_field, value=False
        )
        PersonalDataFieldValue.objects.create(
            facilitator=yes, event=event, field=multi_field, value=["Reds", "Blues"]
        )
        panel_settings = EventPanelSettings.objects.create(event=event)
        panel_settings.displayed_facilitator_fields.add(checkbox_field, multi_field)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitators.html",
            context_data={
                **_base_context(event),
                "facilitators": [
                    FacilitatorListItemDTO(
                        accreditation_type="none",
                        display_name="No",
                        pk=no.pk,
                        slug="no",
                        user_id=None,
                        session_count=0,
                    ),
                    FacilitatorListItemDTO(
                        accreditation_type="none",
                        display_name="Yes",
                        pk=yes.pk,
                        slug="yes",
                        user_id=None,
                        session_count=0,
                    ),
                ],
                "page_obj": PageMatcher(number=1, num_pages=1),
                "displayed_fields": [
                    _field_dto(checkbox_field),
                    _field_dto(multi_field),
                ],
                "column_values": {
                    yes.pk: {"vegan": "Yes", "teams": "Reds, Blues"},
                    no.pk: {"vegan": "No"},
                },
                "filterable_fields": [
                    _field_dto(checkbox_field),
                    _field_dto(multi_field),
                ],
                "filter_fields": {checkbox_field.pk: "", multi_field.pk: ""},
            },
        )

    def test_checkbox_field_filter(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        field = PersonalDataField.objects.create(
            event=event,
            name="Vegan",
            question="Vegan?",
            slug="vegan",
            field_type="checkbox",
            order=0,
        )
        vegan = Facilitator.objects.create(
            event=event, display_name="Vegan", slug="vegan-f", user=None
        )
        PersonalDataFieldValue.objects.create(
            facilitator=vegan, event=event, field=field, value=True
        )
        Facilitator.objects.create(
            event=event, display_name="Omnivore", slug="omni", user=None
        )

        response = authenticated_client.get(
            self.get_url(event), {f"field_{field.pk}": "true"}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitators.html",
            context_data={
                **_base_context(event),
                "facilitators": [
                    FacilitatorListItemDTO(
                        accreditation_type="none",
                        display_name="Vegan",
                        pk=vegan.pk,
                        slug="vegan-f",
                        user_id=None,
                        session_count=0,
                    )
                ],
                "page_obj": PageMatcher(number=1, num_pages=1),
                "filters_active": True,
                "filterable_fields": [_field_dto(field)],
                "filter_fields": {field.pk: "true"},
            },
        )

    def test_select_field_filter(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        field = PersonalDataField.objects.create(
            event=event,
            name="Team",
            question="Team?",
            slug="team",
            field_type="select",
            order=0,
        )
        reds = Facilitator.objects.create(
            event=event, display_name="Reds member", slug="reds", user=None
        )
        PersonalDataFieldValue.objects.create(
            facilitator=reds, event=event, field=field, value="Reds"
        )
        blues = Facilitator.objects.create(
            event=event, display_name="Blues member", slug="blues", user=None
        )
        PersonalDataFieldValue.objects.create(
            facilitator=blues, event=event, field=field, value="Blues"
        )

        response = authenticated_client.get(
            self.get_url(event), {f"field_{field.pk}": "Reds"}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitators.html",
            context_data={
                **_base_context(event),
                "facilitators": [
                    FacilitatorListItemDTO(
                        accreditation_type="none",
                        display_name="Reds member",
                        pk=reds.pk,
                        slug="reds",
                        user_id=None,
                        session_count=0,
                    )
                ],
                "page_obj": PageMatcher(number=1, num_pages=1),
                "filters_active": True,
                "filterable_fields": [_field_dto(field)],
                "filter_fields": {field.pk: "Reds"},
            },
        )

    def test_sort_by_personal_field(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        field = PersonalDataField.objects.create(
            event=event,
            name="Email",
            question="Email?",
            slug="email",
            field_type="text",
            order=0,
        )
        alice = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )
        PersonalDataFieldValue.objects.create(
            facilitator=alice, event=event, field=field, value="zoe@example.com"
        )
        bob = Facilitator.objects.create(
            event=event, display_name="Bob", slug="bob", user=None
        )
        PersonalDataFieldValue.objects.create(
            facilitator=bob, event=event, field=field, value="anna@example.com"
        )

        response = authenticated_client.get(
            self.get_url(event), {"sort": f"field_{field.pk}"}
        )

        # Ascending by email value: anna (Bob) before zoe (Alice).
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitators.html",
            context_data={
                **_base_context(event),
                "facilitators": [
                    FacilitatorListItemDTO(
                        accreditation_type="none",
                        display_name="Bob",
                        pk=bob.pk,
                        slug="bob",
                        user_id=None,
                        session_count=0,
                    ),
                    FacilitatorListItemDTO(
                        accreditation_type="none",
                        display_name="Alice",
                        pk=alice.pk,
                        slug="alice",
                        user_id=None,
                        session_count=0,
                    ),
                ],
                "page_obj": PageMatcher(number=1, num_pages=1),
                "filter_sort": f"field_{field.pk}",
            },
        )

    def test_paginates_facilitators(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        for i in range(_SEED_COUNT):
            Facilitator.objects.create(
                event=event, display_name=f"F{i}", slug=f"f-{i}", user=None
            )

        page1 = authenticated_client.get(self.get_url(event))
        page2 = authenticated_client.get(self.get_url(event), {"page": "2"})

        assert len(page1.context["facilitators"]) == _PAGE_SIZE
        assert page1.context["page_obj"].paginator.num_pages == _TOTAL_PAGES
        assert len(page2.context["facilitators"]) == _LAST_PAGE_COUNT
        assert page2.context["page_obj"].number == _TOTAL_PAGES


class TestFacilitatorActions:
    """Flag / unflag / mark-as-guest POST actions."""

    @staticmethod
    def _facilitator(event, **kwargs):
        defaults = {"display_name": "Alice", "slug": "alice", "user": None}
        defaults.update(kwargs)
        return Facilitator.objects.create(event=event, **defaults)

    @staticmethod
    def _url(name, event, facilitator):
        return reverse(
            name, kwargs={"slug": event.slug, "facilitator_slug": facilitator.slug}
        )

    def test_flag(self, authenticated_client, active_user, sphere, event):
        sphere.managers.add(active_user)
        facilitator = self._facilitator(event)

        response = authenticated_client.post(
            self._url("panel:facilitator-flag", event, facilitator)
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Facilitator flagged for deletion.")],
            url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
        )
        facilitator.refresh_from_db()
        assert facilitator.flagged_for_deletion is True

    def test_unflag(self, authenticated_client, active_user, sphere, event):
        sphere.managers.add(active_user)
        facilitator = self._facilitator(event, flagged_for_deletion=True)

        response = authenticated_client.post(
            self._url("panel:facilitator-unflag", event, facilitator)
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Facilitator unflagged.")],
            url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
        )
        facilitator.refresh_from_db()
        assert facilitator.flagged_for_deletion is False

    def test_mark_guest(self, authenticated_client, active_user, sphere, event):
        sphere.managers.add(active_user)
        facilitator = self._facilitator(event)

        response = authenticated_client.post(
            self._url("panel:facilitator-mark-guest", event, facilitator)
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Facilitator marked as guest.")],
            url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
        )
        facilitator.refresh_from_db()
        assert facilitator.accreditation_type == AccreditationType.GUEST

    def test_mark_guest_is_logged(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        facilitator = self._facilitator(event)

        authenticated_client.post(
            self._url("panel:facilitator-mark-guest", event, facilitator)
        )

        log = FacilitatorChangeLog.objects.get(facilitator=facilitator)
        assert log.user_id == active_user.pk
        assert log.changes == [
            {
                "field": "accreditation_type",
                "field_id": None,
                "old": AccreditationType.NONE.value,
                "new": AccreditationType.GUEST.value,
            }
        ]

    def test_mark_guest_of_already_guest_is_not_logged(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        facilitator = self._facilitator(
            event, accreditation_type=AccreditationType.GUEST
        )

        authenticated_client.post(
            self._url("panel:facilitator-mark-guest", event, facilitator)
        )

        assert not FacilitatorChangeLog.objects.filter(facilitator=facilitator).exists()

    def test_flag_preserves_next(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        facilitator = self._facilitator(event)
        next_url = (
            reverse("panel:facilitators", kwargs={"slug": event.slug})
            + "?flagged=true&sort=-name"
        )

        response = authenticated_client.post(
            self._url("panel:facilitator-flag", event, facilitator), {"next": next_url}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Facilitator flagged for deletion.")],
            url=next_url,
        )

    def test_action_redirects_when_event_not_found(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse(
            "panel:facilitator-flag",
            kwargs={"slug": "nonexistent", "facilitator_slug": "ghost"},
        )

        response = authenticated_client.post(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url=reverse("panel:index"),
        )

    def test_flag_missing_facilitator(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        url = reverse(
            "panel:facilitator-flag",
            kwargs={"slug": event.slug, "facilitator_slug": "ghost"},
        )

        response = authenticated_client.post(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Facilitator not found.")],
            url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
        )

    @pytest.mark.parametrize(
        ("action", "flagged"),
        (
            ("facilitator-flag", False),
            ("facilitator-unflag", True),
            ("facilitator-mark-guest", False),
        ),
    )
    def test_action_on_facilitator_of_another_event_is_not_found(
        self, action, flagged, authenticated_client, active_user, sphere, event
    ):
        # Each action starts from the state it would change, so an unchanged
        # facilitator proves the foreign event was rejected, not that the write
        # was a no-op.
        sphere.managers.add(active_user)
        other_event = EventFactory(sphere=sphere)
        foreign = self._facilitator(
            other_event,
            accreditation_type=AccreditationType.STANDARD,
            flagged_for_deletion=flagged,
        )

        response = authenticated_client.post(
            reverse(
                f"panel:{action}",
                kwargs={"slug": event.slug, "facilitator_slug": foreign.slug},
            )
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Facilitator not found.")],
            url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
        )
        foreign.refresh_from_db()
        assert foreign.flagged_for_deletion is flagged
        assert foreign.accreditation_type == AccreditationType.STANDARD


class TestFacilitatorColumns:
    """Configure which personal-data fields show as list columns."""

    @staticmethod
    def _url(event):
        return reverse("panel:facilitator-columns", kwargs={"slug": event.slug})

    @staticmethod
    def _field(event):
        return PersonalDataField.objects.create(
            event=event,
            name="Email",
            question="Email?",
            slug="email",
            field_type="text",
            order=0,
        )

    def test_get_lists_fields(self, authenticated_client, active_user, sphere, event):
        sphere.managers.add(active_user)
        field = self._field(event)

        response = authenticated_client.get(self._url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-columns.html",
            context_data={
                **_event_context(event),
                "fields": [_field_dto(field)],
                "selected_field_ids": [],
            },
        )

    def test_get_renders_empty_state_without_fields(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self._url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-columns.html",
            context_data={
                **_event_context(event),
                "fields": [],
                "selected_field_ids": [],
            },
            contains="No personal-data fields defined for this event yet.",
        )

    def test_get_redirects_when_event_not_found(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse("panel:facilitator-columns", kwargs={"slug": "nonexistent"})

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url=reverse("panel:index"),
        )

    def test_post_redirects_when_event_not_found(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse("panel:facilitator-columns", kwargs={"slug": "nonexistent"})

        response = authenticated_client.post(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url=reverse("panel:index"),
        )

    def test_post_saves_selection(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        field = self._field(event)

        response = authenticated_client.post(
            self._url(event), {"fields": [str(field.pk)]}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Columns updated.")],
            url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
        )
        settings = EventPanelSettings.objects.get(event=event)
        assert list(
            settings.displayed_facilitator_fields.values_list("pk", flat=True)
        ) == [field.pk]

    def test_post_ignores_unknown_field(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(self._url(event), {"fields": ["99999"]})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Columns updated.")],
            url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
        )
        settings = EventPanelSettings.objects.get(event=event)
        assert settings.displayed_facilitator_fields.count() == 0
