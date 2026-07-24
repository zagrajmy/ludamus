"""Integration tests for /panel/event/<slug>/facilitators/ page."""

from http import HTTPStatus

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.gates.web.django.forms import ACCREDITATION_TYPE_LABELS
from ludamus.links.db.django.models import (
    AccreditationType,
    EventPanelSettings,
    Facilitator,
    FacilitatorChangeLog,
    PersonalDataField,
    PersonalDataFieldValue,
)
from ludamus.pacts import EventDTO, FacilitatorListItemDTO, PersonalDataFieldDTO
from ludamus.pacts.panel import PanelColumnDTO
from tests.integration.conftest import EventFactory
from tests.integration.utils import PageMatcher, assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."

_PAGE_SIZE = 20
_SEED_COUNT = 30
_LAST_PAGE_COUNT = _SEED_COUNT - _PAGE_SIZE
_TOTAL_PAGES = 2
_SMALL_PAGE_SIZE = 10
_SMALL_TOTAL_PAGES = _SEED_COUNT // _SMALL_PAGE_SIZE


def _tab_urls(event):
    return {
        "list": reverse("panel:facilitators", kwargs={"slug": event.slug}),
        "merge": reverse("panel:facilitator-merge", kwargs={"slug": event.slug}),
        "columns": reverse("panel:facilitator-columns", kwargs={"slug": event.slug}),
    }


def _event_context(event, active_tab="list"):
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
        "active_tab": active_tab,
        "tab_urls": _tab_urls(event),
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


_DEFAULT_KEYS = ["name", "linked", "sessions", "accreditation"]
_DEFAULT_COLUMNS = [PanelColumnDTO(key=key) for key in _DEFAULT_KEYS]


def _column_values(facilitators, extra=None):
    # The default columns' rendered strings, keyed by facilitator pk. `extra`
    # adds the personal-data columns a test chose, keyed by pk then column key.
    extra = extra or {}
    return {
        facilitator.pk: {
            "name": facilitator.display_name,
            "linked": "Linked" if facilitator.user_id else "None",
            "sessions": str(facilitator.session_count),
            "accreditation": str(
                ACCREDITATION_TYPE_LABELS[
                    AccreditationType(facilitator.accreditation_type)
                ]
            ),
            **extra.get(facilitator.pk, {}),
        }
        for facilitator in facilitators
    }


def _base_context(event):
    return {
        **_event_context(event),
        "filter_search": "",
        "filter_accreditation": None,
        "filter_flagged": False,
        "filter_sort": "name",
        "filters_active": False,
        "accreditation_types": [
            (t.value, ACCREDITATION_TYPE_LABELS[t]) for t in AccreditationType
        ],
        "columns": _DEFAULT_COLUMNS,
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

        expected = [
            FacilitatorListItemDTO(
                accreditation_type="none",
                display_name="Alice",
                pk=response.context["facilitators"][0].pk,
                slug="alice",
                user_id=None,
                session_count=0,
            )
        ]
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitators.html",
            context_data={
                **_base_context(event),
                "facilitators": expected,
                "column_values": _column_values(expected),
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

        expected = [
            FacilitatorListItemDTO(
                accreditation_type="none",
                display_name="Alice",
                pk=response.context["facilitators"][0].pk,
                slug="alice",
                user_id=None,
                session_count=0,
            )
        ]
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitators.html",
            context_data={
                **_base_context(event),
                "facilitators": expected,
                "column_values": _column_values(expected),
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

        expected = [
            FacilitatorListItemDTO(
                accreditation_type="none",
                display_name="Alice",
                pk=response.context["facilitators"][0].pk,
                slug="alice",
                user_id=None,
                session_count=0,
            )
        ]
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitators.html",
            context_data={
                **_base_context(event),
                "facilitators": expected,
                "column_values": _column_values(expected),
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

        expected = [
            FacilitatorListItemDTO(
                accreditation_type="guest",
                display_name="Guest",
                pk=response.context["facilitators"][0].pk,
                slug="guest",
                user_id=None,
                session_count=0,
            )
        ]
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitators.html",
            context_data={
                **_base_context(event),
                "facilitators": expected,
                "column_values": _column_values(expected),
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
        expected = [
            FacilitatorListItemDTO(
                accreditation_type="none",
                display_name=name,
                pk=listed[index].pk,
                slug=name.lower(),
                user_id=None,
                session_count=0,
            )
            for index, name in enumerate(("Carol", "Bob", "Alice"))
        ]
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitators.html",
            context_data={
                **_base_context(event),
                "facilitators": expected,
                "column_values": _column_values(expected),
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

        expected = [
            FacilitatorListItemDTO(
                accreditation_type="none",
                display_name="Flagged",
                flagged_for_deletion=True,
                pk=response.context["facilitators"][0].pk,
                slug="flagged",
                user_id=None,
                session_count=0,
            )
        ]
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitators.html",
            context_data={
                **_base_context(event),
                "facilitators": expected,
                "column_values": _column_values(expected),
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
        EventPanelSettings.objects.create(
            event=event, facilitator_columns=[*_DEFAULT_KEYS, f"field_{field.pk}"]
        )

        response = authenticated_client.get(self.get_url(event))

        expected = [
            FacilitatorListItemDTO(
                accreditation_type="none",
                display_name="Alice",
                pk=facilitator.pk,
                slug="alice",
                user_id=None,
                session_count=0,
            )
        ]
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitators.html",
            context_data={
                **_base_context(event),
                "facilitators": expected,
                "page_obj": PageMatcher(number=1, num_pages=1),
                "columns": [
                    *_DEFAULT_COLUMNS,
                    PanelColumnDTO(key=f"field_{field.pk}", field=_field_dto(field)),
                ],
                "column_values": _column_values(
                    expected,
                    {facilitator.pk: {f"field_{field.pk}": "alice@example.com"}},
                ),
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
        EventPanelSettings.objects.create(
            event=event,
            facilitator_columns=[
                *_DEFAULT_KEYS,
                f"field_{checkbox_field.pk}",
                f"field_{multi_field.pk}",
            ],
        )

        response = authenticated_client.get(self.get_url(event))

        expected = [
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
        ]
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitators.html",
            context_data={
                **_base_context(event),
                "facilitators": expected,
                "page_obj": PageMatcher(number=1, num_pages=1),
                "columns": [
                    *_DEFAULT_COLUMNS,
                    PanelColumnDTO(
                        key=f"field_{checkbox_field.pk}",
                        field=_field_dto(checkbox_field),
                    ),
                    PanelColumnDTO(
                        key=f"field_{multi_field.pk}", field=_field_dto(multi_field)
                    ),
                ],
                "column_values": _column_values(
                    expected,
                    {
                        yes.pk: {
                            f"field_{checkbox_field.pk}": "Yes",
                            f"field_{multi_field.pk}": "Reds, Blues",
                        },
                        no.pk: {
                            f"field_{checkbox_field.pk}": "No",
                            f"field_{multi_field.pk}": "",
                        },
                    },
                ),
                # multi_field renders as a column but isn't offered as a filter:
                # its stored list can't match the exact-scalar filter.
                "filterable_fields": [_field_dto(checkbox_field)],
                "filter_fields": {checkbox_field.pk: ""},
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

        expected = [
            FacilitatorListItemDTO(
                accreditation_type="none",
                display_name="Vegan",
                pk=vegan.pk,
                slug="vegan-f",
                user_id=None,
                session_count=0,
            )
        ]
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitators.html",
            context_data={
                **_base_context(event),
                "facilitators": expected,
                "column_values": _column_values(expected),
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

        expected = [
            FacilitatorListItemDTO(
                accreditation_type="none",
                display_name="Reds member",
                pk=reds.pk,
                slug="reds",
                user_id=None,
                session_count=0,
            )
        ]
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitators.html",
            context_data={
                **_base_context(event),
                "facilitators": expected,
                "column_values": _column_values(expected),
                "page_obj": PageMatcher(number=1, num_pages=1),
                "filters_active": True,
                "filterable_fields": [_field_dto(field)],
                "filter_fields": {field.pk: "Reds"},
            },
        )

    def test_multi_select_field_is_not_filterable(
        self, authenticated_client, active_user, sphere, event
    ):
        # Multi-select stores a JSON list, which the exact-match filter can
        # never hit, so it must not be offered as a filter at all.
        sphere.managers.add(active_user)
        field = PersonalDataField.objects.create(
            event=event,
            name="Teams",
            question="Teams?",
            slug="teams",
            field_type="select",
            is_multiple=True,
            order=0,
        )
        facilitator = Facilitator.objects.create(
            event=event, display_name="Reds member", slug="reds", user=None
        )
        PersonalDataFieldValue.objects.create(
            facilitator=facilitator, event=event, field=field, value=["Reds"]
        )

        response = authenticated_client.get(
            self.get_url(event), {f"field_{field.pk}": "Reds"}
        )

        expected = [
            FacilitatorListItemDTO(
                accreditation_type="none",
                display_name="Reds member",
                pk=facilitator.pk,
                slug="reds",
                user_id=None,
                session_count=0,
            )
        ]
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitators.html",
            context_data={
                **_base_context(event),
                "facilitators": expected,
                "column_values": _column_values(expected),
                "page_obj": PageMatcher(number=1, num_pages=1),
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

        expected = [
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
        ]
        # Ascending by email value: anna (Bob) before zoe (Alice).
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitators.html",
            context_data={
                **_base_context(event),
                "facilitators": expected,
                "column_values": _column_values(expected),
                "page_obj": PageMatcher(number=1, num_pages=1),
                "filter_sort": f"field_{field.pk}",
            },
        )

    def test_deleted_field_drops_its_column(
        self, authenticated_client, active_user, sphere, event
    ):
        # The key outlives the field it names; the list drops the column rather
        # than failing to render.
        sphere.managers.add(active_user)
        field = PersonalDataField.objects.create(
            event=event,
            name="Email",
            question="Email?",
            slug="email",
            field_type="text",
            order=0,
        )
        EventPanelSettings.objects.create(
            event=event, facilitator_columns=["name", f"field_{field.pk}"]
        )
        field.delete()

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitators.html",
            context_data={
                **_base_context(event),
                "facilitators": [],
                "columns": [PanelColumnDTO(key="name")],
                "page_obj": PageMatcher(number=1, num_pages=1),
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

    def test_page_size_param(self, authenticated_client, active_user, sphere, event):
        sphere.managers.add(active_user)
        for i in range(_SEED_COUNT):
            Facilitator.objects.create(
                event=event, display_name=f"F{i}", slug=f"f-{i}", user=None
            )

        smaller = authenticated_client.get(self.get_url(event), {"page_size": "10"})
        unlisted = authenticated_client.get(self.get_url(event), {"page_size": "7"})

        assert smaller.context["page_obj"].paginator.per_page == _SMALL_PAGE_SIZE
        assert smaller.context["page_obj"].paginator.num_pages == _SMALL_TOTAL_PAGES
        assert unlisted.context["page_obj"].paginator.per_page == _PAGE_SIZE


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

    _ACTION_NAMES = (
        "panel:facilitator-flag",
        "panel:facilitator-unflag",
        "panel:facilitator-mark-guest",
    )

    @pytest.mark.parametrize("name", _ACTION_NAMES)
    def test_redirects_anonymous_user_to_login(self, client, event, name):
        facilitator = self._facilitator(event)
        url = self._url(name, event, facilitator)

        response = client.post(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    @pytest.mark.parametrize("name", _ACTION_NAMES)
    def test_redirects_non_manager_user(self, authenticated_client, event, name):
        facilitator = self._facilitator(event)

        response = authenticated_client.post(self._url(name, event, facilitator))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
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
    """Configure which columns show on the list, and in what order."""

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

    @pytest.mark.parametrize("method", ("get", "post"))
    def test_redirects_anonymous_user_to_login(self, client, event, method):
        url = self._url(event)

        response = getattr(client, method)(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    @pytest.mark.parametrize("method", ("get", "post"))
    def test_redirects_non_manager_user(self, authenticated_client, event, method):
        response = getattr(authenticated_client, method)(self._url(event))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_get_offers_builtin_and_field_columns(
        self, authenticated_client, active_user, sphere, event
    ):
        # Nothing chosen yet: the defaults are the chosen set, and the event's
        # own personal-data field is what's left to add.
        sphere.managers.add(active_user)
        field = self._field(event)

        response = authenticated_client.get(self._url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-columns.html",
            context_data={
                **_event_context(event, active_tab="columns"),
                "chosen_columns": _DEFAULT_COLUMNS,
                "available_columns": [
                    PanelColumnDTO(key=f"field_{field.pk}", field=_field_dto(field))
                ],
                "error": None,
            },
        )

    def test_get_offers_only_builtins_without_fields(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self._url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-columns.html",
            context_data={
                **_event_context(event, active_tab="columns"),
                "chosen_columns": _DEFAULT_COLUMNS,
                "available_columns": [],
                "error": None,
            },
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

    def test_post_saves_chosen_columns_in_order(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        field = self._field(event)

        response = authenticated_client.post(
            self._url(event), {"columns": [f"field_{field.pk}", "sessions"]}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Columns updated.")],
            url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
        )
        settings = EventPanelSettings.objects.get(event=event)
        assert settings.facilitator_columns == [f"field_{field.pk}", "sessions"]

    def test_post_rejects_a_selection_with_no_valid_column(
        self, authenticated_client, active_user, sphere, event
    ):
        # Unticking everything used to save "[]", which reads back as "use the
        # defaults" — the organizer saw every default column return instead.
        sphere.managers.add(active_user)
        EventPanelSettings.objects.create(event=event, facilitator_columns=["name"])

        response = authenticated_client.post(self._url(event), {"columns": ["bogus"]})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-columns.html",
            context_data={
                **_event_context(event, active_tab="columns"),
                "chosen_columns": [PanelColumnDTO(key="name")],
                "available_columns": [
                    PanelColumnDTO(key=key)
                    for key in ("linked", "sessions", "accreditation")
                ],
                "error": "Pick at least one column to show.",
            },
        )
        settings = EventPanelSettings.objects.get(event=event)
        assert settings.facilitator_columns == ["name"]

    def test_post_replaces_the_previous_set(
        self, authenticated_client, active_user, sphere, event
    ):
        # Saving is a replace, not an add: the defaults go when they aren't
        # among the chosen keys.
        sphere.managers.add(active_user)
        EventPanelSettings.objects.create(
            event=event, facilitator_columns=_DEFAULT_KEYS
        )

        response = authenticated_client.post(self._url(event), {"columns": ["name"]})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Columns updated.")],
            url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
        )
        settings = EventPanelSettings.objects.get(event=event)
        assert settings.facilitator_columns == ["name"]

    def test_post_ignores_unknown_and_duplicate_keys(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            self._url(event), {"columns": ["field_99999", "bogus", "name", "name"]}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Columns updated.")],
            url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
        )
        settings = EventPanelSettings.objects.get(event=event)
        assert settings.facilitator_columns == ["name"]

    def test_post_ignores_a_foreign_events_field(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        foreign_field = self._field(EventFactory(sphere=sphere))

        response = authenticated_client.post(
            self._url(event), {"columns": ["name", f"field_{foreign_field.pk}"]}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Columns updated.")],
            url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
        )
        settings = EventPanelSettings.objects.get(event=event)
        assert settings.facilitator_columns == ["name"]
