from http import HTTPStatus

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import (
    EventPanelSettings,
    Session,
    SessionField,
    SessionFieldValue,
)
from ludamus.pacts import (
    EventDTO,
    ProposalCategoryDTO,
    SessionFieldDTO,
    SessionListItemDTO,
    SessionStatus,
)
from ludamus.pacts.panel import PanelColumnDTO
from tests.integration.conftest import EventFactory
from tests.integration.utils import PageMatcher, assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."

_DEFAULT_KEYS = ["title", "host", "category", "status", "created"]
_DEFAULT_COLUMNS = [PanelColumnDTO(key=key) for key in _DEFAULT_KEYS]


def _field_dto(field):
    return SessionFieldDTO(
        pk=field.pk,
        name=field.name,
        question=field.question,
        slug=field.slug,
        field_type=field.field_type,
        order=field.order,
    )


def _base_context(event, active_tab="columns"):
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
        "active_nav": "proposals",
        "active_tab": active_tab,
        "tab_urls": {
            "list": reverse("panel:proposals", kwargs={"slug": event.slug}),
            "columns": reverse("panel:proposal-columns", kwargs={"slug": event.slug}),
        },
    }


def _list_page_context(event, *, category, session, columns, column_values):
    return {
        **_base_context(event, active_tab="list"),
        "deleted_proposals": [],
        "all_tracks": [],
        "managed_track_pks": set(),
        "filter_track_pk": None,
        "filter_track_multi": False,
        "filter_track_value": "",
        "page_obj": PageMatcher(number=1, num_pages=1),
        "filter_category_pk": None,
        "filter_status": None,
        "filter_sort": "",
        "statuses": [
            ("pending", "Pending"),
            ("accepted", "Accepted"),
            ("on_hold", "On hold"),
            ("rejected", "Rejected"),
            ("scheduled", "Scheduled"),
        ],
        "stats": {
            "hosts_count": 0,
            "pending_proposals": 1,
            "rooms_count": 0,
            "scheduled_sessions": 0,
            "total_proposals": 1,
            "total_sessions": 1,
        },
        "categories": [ProposalCategoryDTO.model_validate(category)],
        "columns": columns,
        "column_values": column_values,
        "proposals": [
            SessionListItemDTO(
                pk=session.pk,
                title=session.title,
                display_name=session.display_name,
                category_name=category.name,
                status=SessionStatus.PENDING,
                creation_time=session.creation_time,
                is_scheduled=False,
            )
        ],
        "session_fields": [],
        "filter_fields": {},
        "filter_search": "",
    }


class TestProposalColumnsPageView:
    """Configure which columns show on the proposals list, and in what order."""

    @staticmethod
    def _url(event):
        return reverse("panel:proposal-columns", kwargs={"slug": event.slug})

    @staticmethod
    def _field(event):
        return SessionField.objects.create(
            event=event,
            name="System",
            question="What system?",
            slug="system",
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

    @pytest.mark.parametrize("method", ("get", "post"))
    def test_redirects_when_event_not_found(
        self, authenticated_client, active_user, sphere, method
    ):
        sphere.managers.add(active_user)
        url = reverse("panel:proposal-columns", kwargs={"slug": "nonexistent"})

        response = getattr(authenticated_client, method)(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url=reverse("panel:index"),
        )

    def test_get_offers_builtin_and_field_columns(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        field = self._field(event)

        response = authenticated_client.get(self._url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-columns.html",
            context_data={
                **_base_context(event),
                "chosen_columns": _DEFAULT_COLUMNS,
                "available_columns": [
                    PanelColumnDTO(key=f"field_{field.pk}", field=_field_dto(field))
                ],
            },
        )

    def test_post_saves_chosen_columns_in_order(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        field = self._field(event)

        response = authenticated_client.post(
            self._url(event), {"columns": [f"field_{field.pk}", "title"]}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Columns updated.")],
            url=reverse("panel:proposals", kwargs={"slug": event.slug}),
        )
        settings = EventPanelSettings.objects.get(event=event)
        assert settings.proposal_columns == [f"field_{field.pk}", "title"]

    def test_post_ignores_unknown_duplicate_and_foreign_keys(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        foreign_field = self._field(EventFactory(sphere=sphere))

        response = authenticated_client.post(
            self._url(event),
            {"columns": ["bogus", "title", "title", f"field_{foreign_field.pk}"]},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Columns updated.")],
            url=reverse("panel:proposals", kwargs={"slug": event.slug}),
        )
        settings = EventPanelSettings.objects.get(event=event)
        assert settings.proposal_columns == ["title"]

    def test_field_column_shows_values_on_the_list(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        field = self._field(event)
        EventPanelSettings.objects.create(
            event=event, proposal_columns=["title", f"field_{field.pk}"]
        )
        session = Session.objects.create(
            event=event,
            category=proposal_category,
            display_name="Host",
            title="Dragon Heist",
            slug="dragon-heist",
            participants_limit=5,
            status="pending",
        )
        SessionFieldValue.objects.create(session=session, field=field, value="D&D 5e")

        response = authenticated_client.get(
            reverse("panel:proposals", kwargs={"slug": event.slug})
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposals.html",
            contains="D&amp;D 5e",
            context_data=_list_page_context(
                event,
                category=proposal_category,
                session=session,
                columns=[
                    PanelColumnDTO(key="title"),
                    PanelColumnDTO(key=f"field_{field.pk}", field=_field_dto(field)),
                ],
                column_values={session.pk: {f"field_{field.pk}": "D&D 5e"}},
            ),
        )

    def test_checkbox_value_renders_as_text(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        checkbox = SessionField.objects.create(
            event=event,
            name="Online",
            question="Online?",
            slug="online",
            field_type="checkbox",
            order=0,
        )
        EventPanelSettings.objects.create(
            event=event, proposal_columns=["title", f"field_{checkbox.pk}"]
        )
        session = Session.objects.create(
            event=event,
            category=proposal_category,
            display_name="Host",
            title="Dragon Heist",
            slug="dragon-heist",
            participants_limit=5,
            status="pending",
        )
        SessionFieldValue.objects.create(session=session, field=checkbox, value=True)

        response = authenticated_client.get(
            reverse("panel:proposals", kwargs={"slug": event.slug})
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposals.html",
            context_data=_list_page_context(
                event,
                category=proposal_category,
                session=session,
                columns=[
                    PanelColumnDTO(key="title"),
                    PanelColumnDTO(
                        key=f"field_{checkbox.pk}", field=_field_dto(checkbox)
                    ),
                ],
                column_values={session.pk: {f"field_{checkbox.pk}": "✓"}},
            ),
        )
