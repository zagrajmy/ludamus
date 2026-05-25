"""Integration tests for the Import / Export panel section.

Import lives in its own section, not under integrations settings; the
integration is just the connection it pulls through.
"""

from __future__ import annotations

import json
from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import (
    EventIntegration,
    Session,
    SessionField,
    SessionFieldValue,
)
from ludamus.pacts import EventDTO
from ludamus.pacts.chronology import (
    EventIntegrationDTO,
    IntegrationImplementationId,
    IntegrationKind,
)
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."
IMPL = IntegrationImplementationId.GOOGLE_PROPOSAL_PULLER
CONFIG_JSON = json.dumps({"sheet_id": "sheet-1", "form_id": "form-1"})
EMPTY_STATS = {
    "hosts_count": 0,
    "pending_proposals": 0,
    "rooms_count": 0,
    "scheduled_sessions": 0,
    "total_proposals": 0,
    "total_sessions": 0,
}


def _import_url(event) -> str:
    return reverse("panel:import", kwargs={"slug": event.slug})


def _tab_url(event, integration) -> str:
    return reverse(
        "panel:import-integration", kwargs={"slug": event.slug, "pk": integration.pk}
    )


def _run_url(event, integration) -> str:
    return reverse(
        "panel:import-run", kwargs={"slug": event.slug, "pk": integration.pk}
    )


def _event_context(event) -> dict[str, object]:
    return {
        "current_event": EventDTO.model_validate(event),
        "events": [EventDTO.model_validate(event)],
        "is_proposal_active": False,
        "stats": EMPTY_STATS,
    }


def _make_import_integration(event, connection, *, display_name: str):
    return EventIntegration.objects.create(
        event=event,
        kind=IntegrationKind.IMPORT.value,
        implementation=IMPL.value,
        connection=connection,
        display_name=display_name,
        config_json=CONFIG_JSON,
    )


def _dto(integration) -> EventIntegrationDTO:
    return EventIntegrationDTO(
        pk=integration.pk,
        event_id=integration.event_id,
        kind=IntegrationKind(integration.kind),
        implementation=IntegrationImplementationId(integration.implementation),
        connection_id=integration.connection_id,
        connection_display_name=integration.connection.display_name,
        display_name=integration.display_name,
        config_json=integration.config_json,
        settings_json=integration.settings_json,
    )


@pytest.mark.django_db
class TestEventImportSectionView:
    def test_get_redirects_anonymous(self, client, event):
        url = _import_url(event)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_get_redirects_non_manager(self, authenticated_client, event):
        response = authenticated_client.get(_import_url(event))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_get_renders_empty_state_without_import_integrations(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(_import_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/import.html",
            context_data=_event_context(event)
            | {"active_nav": "import", "active_integration": None},
        )

    def test_get_lists_questions_as_recipe_rows_under_a_tab(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.return_value = MagicMock(
                ok=True,
                json=lambda: {
                    "items": [
                        {"title": "Title", "questionItem": {"question": {}}},
                        {"title": "Section header"},
                        {"title": "System", "questionItem": {"question": {}}},
                    ]
                },
            )
            response = authenticated_client.get(_tab_url(event, integration))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/import.html",
            context_data=_event_context(event)
            | {
                "active_nav": "import",
                "active_integration": _dto(integration),
                "session_columns": ("title", "description"),
                "rows": [
                    {
                        "index": 0,
                        "question": "Title",
                        "selected": "ignore",
                        "field_name": "",
                    },
                    {
                        "index": 1,
                        "question": "System",
                        "selected": "ignore",
                        "field_name": "",
                    },
                ],
            },
        )

    def test_get_without_pk_defaults_to_first_integration(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.return_value = MagicMock(
                ok=True,
                json=lambda: {
                    "items": [{"title": "Title", "questionItem": {"question": {}}}]
                },
            )
            response = authenticated_client.get(_import_url(event))

        assert response.status_code == HTTPStatus.OK
        assert response.context_data["active_integration"] == _dto(integration)

    def test_get_unknown_integration_redirects_to_section(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        _make_import_integration(event, connection_with_secret, display_name="Puller")

        response = authenticated_client.get(
            reverse(
                "panel:import-integration", kwargs={"slug": event.slug, "pk": 99999}
            )
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_import_url(event),
            messages=[(messages.ERROR, "Import integration not found.")],
        )

    def test_post_saves_recipe_to_settings(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        response = authenticated_client.post(
            _tab_url(event, integration),
            data={
                "question_0": "Title",
                "target_0": "session.title",
                "question_1": "System",
                "target_1": "field",
                "newname_1": "System",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_tab_url(event, integration),
            messages=[(messages.SUCCESS, "Import recipe saved.")],
        )
        integration.refresh_from_db()
        assert json.loads(integration.settings_json) == {
            "questions": {
                "Title": {"to": "session.title", "ignore": False},
                "System": {"to": "field.System", "ignore": False},
            }
        }


@pytest.mark.django_db
class TestEventImportRunActionView:
    def test_post_redirects_non_manager(self, authenticated_client, event, connection):
        integration = _make_import_integration(event, connection, display_name="Puller")

        response = authenticated_client.post(_run_url(event, integration))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_post_creates_one_proposal_per_response(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        integration.settings_json = json.dumps(
            {"questions": {"Title": {"to": "session.title", "ignore": False}}}
        )
        integration.save(update_fields=["settings_json"])

        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.return_value = MagicMock(
                ok=True, json=lambda: {"values": [["Title"], ["My Talk"], ["Another"]]}
            )
            response = authenticated_client.post(_run_url(event, integration))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_tab_url(event, integration),
            messages=[(messages.SUCCESS, "Created 2 proposals.")],
        )
        titles = set(
            Session.objects.filter(sphere=sphere).values_list("title", flat=True)
        )
        assert titles == {"My Talk", "Another"}

    def test_post_provisions_a_new_field_and_fills_it(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        integration.settings_json = json.dumps(
            {
                "questions": {
                    "Title": {"to": "session.title", "ignore": False},
                    "RPG system": {"to": "field.System", "ignore": False},
                }
            }
        )
        integration.save(update_fields=["settings_json"])

        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.return_value = MagicMock(
                ok=True,
                json=lambda: {"values": [["Title", "RPG system"], ["My Talk", "D&D"]]},
            )
            response = authenticated_client.post(_run_url(event, integration))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_tab_url(event, integration),
            messages=[(messages.SUCCESS, "Created 1 proposals.")],
        )
        field = SessionField.objects.get(event=event, slug="system")
        assert field.name == "System"
        assert field.question == "RPG system"
        session = Session.objects.get(sphere=sphere, title="My Talk")
        value = SessionFieldValue.objects.get(session=session, field=field)
        assert value.value == "D&D"
