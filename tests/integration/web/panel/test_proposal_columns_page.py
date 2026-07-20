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
from ludamus.pacts import EventDTO, SessionFieldDTO
from ludamus.pacts.chronology import ProposalColumnDTO
from tests.integration.conftest import EventFactory
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."

_DEFAULT_KEYS = ["title", "host", "category", "status", "created"]
_DEFAULT_COLUMNS = [ProposalColumnDTO(key=key) for key in _DEFAULT_KEYS]


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
                    ProposalColumnDTO(key=f"field_{field.pk}", field=_field_dto(field))
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

        assert response.status_code == HTTPStatus.OK
        assert response.context["columns"] == [
            ProposalColumnDTO(key="title"),
            ProposalColumnDTO(key=f"field_{field.pk}", field=_field_dto(field)),
        ]
        assert response.context["column_values"] == {
            session.pk: {f"field_{field.pk}": "D&D 5e"}
        }
        assert "D&amp;D 5e" in response.content.decode()
