"""Integration tests for the event-integration CRUD + check views."""

from __future__ import annotations

import json
from http import HTTPStatus
from unittest.mock import ANY, MagicMock, patch

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import EventIntegration
from ludamus.gates.web.django.chronology.panel.forms import integration_signature
from ludamus.gates.web.django.chronology.panel.views.base import settings_tab_urls
from ludamus.pacts import EventDTO
from ludamus.pacts.chronology import (
    EventIntegrationDTO,
    IntegrationImplementationId,
    IntegrationKind,
)
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."
IMPL = IntegrationImplementationId.GOOGLE_PROPOSAL_PULLER
CONFIG = {"sheet_id": "sheet-1", "form_id": "form-1"}
CONFIG_JSON = json.dumps(CONFIG)
EMPTY_STATS = {
    "hosts_count": 0,
    "pending_proposals": 0,
    "rooms_count": 0,
    "scheduled_sessions": 0,
    "total_proposals": 0,
    "total_sessions": 0,
}


def _settings_url(event) -> str:
    return reverse("panel:event-integration-settings", kwargs={"slug": event.slug})


def _create_url(event) -> str:
    return reverse("panel:integration-create", kwargs={"slug": event.slug})


def _edit_url(event, integration) -> str:
    return reverse(
        "panel:integration-edit", kwargs={"slug": event.slug, "pk": integration.pk}
    )


def _delete_url(event, integration) -> str:
    return reverse(
        "panel:integration-delete", kwargs={"slug": event.slug, "pk": integration.pk}
    )


def _check_url(event) -> str:
    return reverse("panel:integration-check", kwargs={"slug": event.slug})


def _missing_url(name: str, **kwargs) -> str:
    return reverse(name, kwargs={"slug": "missing", **kwargs})


def _event_context(event) -> dict[str, object]:
    # The shared `get_event_context` slice every panel page carries.
    return {
        "current_event": EventDTO.model_validate(event),
        "events": [EventDTO.model_validate(event)],
        "is_proposal_active": False,
        "stats": EMPTY_STATS,
    }


def _make_integration(event, connection, *, display_name: str) -> EventIntegration:
    return EventIntegration.objects.create(
        event=event,
        kind=IntegrationKind.IMPORT.value,
        implementation=IMPL.value,
        connection=connection,
        display_name=display_name,
        config_json=CONFIG_JSON,
    )


def _dto(integration: EventIntegration) -> EventIntegrationDTO:
    return EventIntegrationDTO(
        pk=integration.pk,
        event_id=integration.event_id,
        kind=IntegrationKind(integration.kind),
        implementation=IntegrationImplementationId(integration.implementation),
        connection_id=integration.connection_id,
        connection_display_name=integration.connection.display_name,
        display_name=integration.display_name,
        config_json=integration.config_json,
    )


@pytest.mark.django_db
class TestEventIntegrationSettingsPageView:
    def test_get_redirects_anonymous(self, client, event):
        url = _settings_url(event)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_get_redirects_non_manager(self, authenticated_client, event):
        response = authenticated_client.get(_settings_url(event))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_get_redirects_on_unknown_event(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(
            _missing_url("panel:event-integration-settings")
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_get_renders_empty_settings_page(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(_settings_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/integration-settings.html",
            context_data=_event_context(event)
            | {
                "active_nav": "settings",
                "active_tab": "integrations",
                "tab_urls": settings_tab_urls(event.slug),
                "integrations": [],
            },
        )

    def test_get_renders_settings_page(
        self, authenticated_client, active_user, sphere, event, connection
    ):
        sphere.managers.add(active_user)
        integration = _make_integration(event, connection, display_name="Listed")

        response = authenticated_client.get(_settings_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/integration-settings.html",
            context_data=_event_context(event)
            | {
                "active_nav": "settings",
                "active_tab": "integrations",
                "tab_urls": settings_tab_urls(event.slug),
                "integrations": [_dto(integration)],
            },
        )


@pytest.mark.django_db
class TestIntegrationCreatePageView:
    def test_get_redirects_anonymous(self, client, event):
        url = _create_url(event)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_get_redirects_non_manager(self, authenticated_client, event):
        response = authenticated_client.get(_create_url(event))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_get_renders_form(self, authenticated_client, active_user, sphere, event):
        sphere.managers.add(active_user)

        response = authenticated_client.get(_create_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/panel/integrations/create.html",
            context_data=_event_context(event)
            | {"active_nav": "settings", "form": ANY},
        )

    def test_get_redirects_on_unknown_event(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(_missing_url("panel:integration-create"))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_post_redirects_on_unknown_event(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            _missing_url("panel:integration-create"), data={}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_post_creates_integration_when_check_signature_matches(
        self, authenticated_client, active_user, sphere, event, connection
    ):
        sphere.managers.add(active_user)
        signature = integration_signature(connection.pk, CONFIG_JSON)

        response = authenticated_client.post(
            _create_url(event),
            data={
                "display_name": "Main import",
                "implementation": IMPL.value,
                "connection": str(connection.pk),
                "config_json": CONFIG_JSON,
                "last_ok_signature": signature,
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Integration created.")],
            url=_settings_url(event),
        )
        assert EventIntegration.objects.filter(
            event=event, display_name="Main import"
        ).exists()

    def test_post_refuses_when_check_signature_missing(
        self, authenticated_client, active_user, sphere, event, connection
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            _create_url(event),
            data={
                "display_name": "No check",
                "implementation": IMPL.value,
                "connection": str(connection.pk),
                "config_json": CONFIG_JSON,
                "last_ok_signature": "",
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/panel/integrations/create.html",
            context_data=_event_context(event)
            | {"active_nav": "settings", "form": ANY},
        )
        assert not EventIntegration.objects.filter(
            event=event, display_name="No check"
        ).exists()

    def test_post_invalid_json_renders_form_with_error(
        self, authenticated_client, active_user, sphere, event, connection
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            _create_url(event),
            data={
                "display_name": "Bad JSON",
                "implementation": IMPL.value,
                "connection": str(connection.pk),
                "config_json": "{not-json",
                "last_ok_signature": "",
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/panel/integrations/create.html",
            context_data=_event_context(event)
            | {"active_nav": "settings", "form": ANY},
        )
        assert "config_json" in response.context["form"].errors

    def test_post_non_dict_json_renders_form_with_error(
        self, authenticated_client, active_user, sphere, event, connection
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            _create_url(event),
            data={
                "display_name": "Array JSON",
                "implementation": IMPL.value,
                "connection": str(connection.pk),
                "config_json": "[]",
                "last_ok_signature": "",
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/panel/integrations/create.html",
            context_data=_event_context(event)
            | {"active_nav": "settings", "form": ANY},
        )
        assert "config_json" in response.context["form"].errors

    def test_post_config_fails_pydantic_validation(
        self, authenticated_client, active_user, sphere, event, connection
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            _create_url(event),
            data={
                "display_name": "Pydantic fail",
                "implementation": IMPL.value,
                "connection": str(connection.pk),
                # missing required "sheet_id" / "form_id" fields
                "config_json": "{}",
                "last_ok_signature": "",
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/panel/integrations/create.html",
            context_data=_event_context(event)
            | {"active_nav": "settings", "form": ANY},
        )
        form = response.context["form"]
        assert "config_json" in form.errors
        # _attach_pydantic_errors prefixes each error with its field path.
        joined = " ".join(str(e) for e in form.errors["config_json"])
        assert "sheet_id" in joined

    def test_post_missing_display_name_renders_form_with_error(
        self, authenticated_client, active_user, sphere, event, connection
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            _create_url(event),
            data={
                "display_name": "",
                "implementation": IMPL.value,
                "connection": str(connection.pk),
                "config_json": CONFIG_JSON,
                "last_ok_signature": "",
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/panel/integrations/create.html",
            context_data=_event_context(event)
            | {"active_nav": "settings", "form": ANY},
        )
        assert "display_name" in response.context["form"].errors

    def test_post_invalid_implementation_renders_form_with_error(
        self, authenticated_client, active_user, sphere, event, connection
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            _create_url(event),
            data={
                "display_name": "Bad impl",
                "implementation": "not-a-real-impl",
                "connection": str(connection.pk),
                "config_json": CONFIG_JSON,
                "last_ok_signature": "",
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/panel/integrations/create.html",
            context_data=_event_context(event)
            | {"active_nav": "settings", "form": ANY},
        )
        assert "implementation" in response.context["form"].errors

    def test_post_invalid_connection_renders_form_with_error(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            _create_url(event),
            data={
                "display_name": "Bad conn",
                "implementation": IMPL.value,
                "connection": "99999",
                "config_json": CONFIG_JSON,
                "last_ok_signature": "",
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/panel/integrations/create.html",
            context_data=_event_context(event)
            | {"active_nav": "settings", "form": ANY},
        )
        assert "connection" in response.context["form"].errors

    def test_post_duplicate_display_name_for_kind(
        self, authenticated_client, active_user, sphere, event, connection
    ):
        sphere.managers.add(active_user)
        _make_integration(event, connection, display_name="Taken")
        signature = integration_signature(connection.pk, CONFIG_JSON)

        response = authenticated_client.post(
            _create_url(event),
            data={
                "display_name": "Taken",
                "implementation": IMPL.value,
                "connection": str(connection.pk),
                "config_json": CONFIG_JSON,
                "last_ok_signature": signature,
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/panel/integrations/create.html",
            context_data=_event_context(event)
            | {"active_nav": "settings", "form": ANY},
        )
        assert "display_name" in response.context["form"].errors


@pytest.mark.django_db
class TestIntegrationEditPageView:
    def test_get_renders_form(
        self, authenticated_client, active_user, sphere, event, connection
    ):
        sphere.managers.add(active_user)
        integration = _make_integration(event, connection, display_name="Existing")

        response = authenticated_client.get(_edit_url(event, integration))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/panel/integrations/edit.html",
            context_data=_event_context(event)
            | {"active_nav": "settings", "form": ANY, "integration": _dto(integration)},
        )

    def test_post_display_name_only_bypasses_check(
        self, authenticated_client, active_user, sphere, event, connection
    ):
        sphere.managers.add(active_user)
        integration = _make_integration(event, connection, display_name="Old name")

        response = authenticated_client.post(
            _edit_url(event, integration),
            data={
                "display_name": "New name",
                "implementation": IMPL.value,
                "connection": str(connection.pk),
                "config_json": CONFIG_JSON,
                "last_ok_signature": "",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Integration updated.")],
            url=_settings_url(event),
        )
        integration.refresh_from_db()
        assert integration.display_name == "New name"

    def test_get_redirects_on_unknown_event(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(
            _missing_url("panel:integration-edit", pk=1)
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_get_redirects_on_unknown_integration(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        url = reverse(
            "panel:integration-edit", kwargs={"slug": event.slug, "pk": 99999}
        )

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Integration not found.")],
            url=_settings_url(event),
        )

    def test_post_redirects_on_unknown_event(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            _missing_url("panel:integration-edit", pk=1), data={}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_post_invalid_form_renders_with_errors(
        self, authenticated_client, active_user, sphere, event, connection
    ):
        sphere.managers.add(active_user)
        integration = _make_integration(event, connection, display_name="To edit")

        response = authenticated_client.post(
            _edit_url(event, integration),
            data={
                "display_name": "",  # required field missing → invalid form
                "implementation": IMPL.value,
                "connection": str(connection.pk),
                "config_json": CONFIG_JSON,
                "last_ok_signature": "",
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/panel/integrations/edit.html",
            context_data=_event_context(event)
            | {"active_nav": "settings", "form": ANY, "integration": _dto(integration)},
        )
        assert "display_name" in response.context["form"].errors


@pytest.mark.django_db
class TestIntegrationDeletePageView:
    def test_post_deletes(
        self, authenticated_client, active_user, sphere, event, connection
    ):
        sphere.managers.add(active_user)
        integration = _make_integration(event, connection, display_name="Goodbye")

        response = authenticated_client.post(_delete_url(event, integration))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Integration deleted.")],
            url=_settings_url(event),
        )
        assert not EventIntegration.objects.filter(pk=integration.pk).exists()

    def test_get_renders_confirmation(
        self, authenticated_client, active_user, sphere, event, connection
    ):
        sphere.managers.add(active_user)
        integration = _make_integration(event, connection, display_name="Confirm me")

        response = authenticated_client.get(_delete_url(event, integration))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/panel/integrations/delete.html",
            context_data=_event_context(event)
            | {"active_nav": "settings", "integration": _dto(integration)},
        )

    def test_get_redirects_on_unknown_event(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(
            _missing_url("panel:integration-delete", pk=1)
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_get_redirects_on_unknown_integration(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        url = reverse(
            "panel:integration-delete", kwargs={"slug": event.slug, "pk": 99999}
        )

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Integration not found.")],
            url=_settings_url(event),
        )

    def test_post_redirects_on_unknown_event(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            _missing_url("panel:integration-delete", pk=1), data={}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )


@pytest.mark.django_db
class TestIntegrationCheckActionView:
    def test_post_ok_returns_signature(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)

        # Mock only google.auth: real GoogleDocsProposalImporter._probe runs and
        # maps the (mocked) HTTP response — we never patch project code.
        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.return_value = MagicMock(ok=True)
            response = authenticated_client.post(
                _check_url(event),
                data={
                    "implementation": IMPL.value,
                    "connection": str(connection_with_secret.pk),
                    "config_json": CONFIG_JSON,
                },
            )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/panel/integrations/_check_result.html",
            context_data={
                "passed": True,
                "hint": "",
                "signature": integration_signature(
                    connection_with_secret.pk, CONFIG_JSON
                ),
            },
        )

    def test_post_unknown_event_returns_bad_request(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            _missing_url("panel:integration-check"), data={}
        )

        assert_response(
            response,
            HTTPStatus.BAD_REQUEST,
            messages=[(messages.ERROR, "Event not found.")],
        )
        assert response.content == b"Unknown event"

    def test_post_missing_implementation_reports_failure(
        self, authenticated_client, active_user, sphere, event, connection
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            _check_url(event),
            data={
                "implementation": "",
                "connection": str(connection.pk),
                "config_json": "{}",
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/panel/integrations/_check_result.html",
            context_data={
                "passed": False,
                "hint": (
                    "Pick an implementation and a connection before running the check."
                ),
                "signature": "",
            },
        )

    def test_post_missing_connection_reports_failure(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            _check_url(event),
            data={"implementation": IMPL.value, "connection": "", "config_json": "{}"},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/panel/integrations/_check_result.html",
            context_data={
                "passed": False,
                "hint": (
                    "Pick an implementation and a connection before running the check."
                ),
                "signature": "",
            },
        )

    def test_post_unknown_implementation_reports_failure(
        self, authenticated_client, active_user, sphere, event, connection
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            _check_url(event),
            data={
                "implementation": "not-a-real-impl",
                "connection": str(connection.pk),
                "config_json": "{}",
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/panel/integrations/_check_result.html",
            context_data={
                "passed": False,
                "hint": "Unknown implementation: not-a-real-impl",
                "signature": "",
            },
        )

    def test_post_bad_connection_id_returns_bad_request(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            _check_url(event),
            data={
                "implementation": IMPL.value,
                "connection": "not-a-number",
                "config_json": "{}",
            },
        )

        assert_response(response, HTTPStatus.BAD_REQUEST)
        assert response.content == b"Bad connection id"

    def test_post_invalid_json_reports_failure(
        self, authenticated_client, active_user, sphere, event, connection
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            _check_url(event),
            data={
                "implementation": IMPL.value,
                "connection": str(connection.pk),
                "config_json": "{bad-json",
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/panel/integrations/_check_result.html",
            context_data={
                "passed": False,
                "hint": (
                    "Expecting property name enclosed in double quotes: "
                    "line 1 column 2 (char 1)"
                ),
                "signature": "",
            },
        )

    def test_post_non_dict_json_reports_failure(
        self, authenticated_client, active_user, sphere, event, connection
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            _check_url(event),
            data={
                "implementation": IMPL.value,
                "connection": str(connection.pk),
                "config_json": "[]",
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/panel/integrations/_check_result.html",
            context_data={
                "passed": False,
                "hint": "Configuration must be a JSON object.",
                "signature": "",
            },
        )
