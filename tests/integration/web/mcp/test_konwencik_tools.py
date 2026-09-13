import json
from datetime import UTC, datetime
from http import HTTPStatus

import pytest

from ludamus.gates.web.django.mcp.tokens import mint_organizer_token
from ludamus.links.db.django.models import Connection, EventIntegration, Track
from ludamus.pacts.chronology import IntegrationImplementationId, IntegrationKind
from ludamus.pacts.konwencik import KonwencikExportSettings
from tests.integration.conftest import (
    EventFactory,
    ProposalCategoryFactory,
    UserFactory,
)
from tests.integration.utils import assert_response
from tests.integration.web.mcp.test_mcp_endpoint import tool_text
from tests.integration.web.mcp.test_mcp_organizer_endpoint import call_org_tool


@pytest.fixture(name="token")
def token_fixture(sphere, event):
    manager = UserFactory()
    sphere.managers.add(manager)
    return mint_organizer_token(
        user_id=manager.pk, sphere_id=sphere.pk, event_id=event.pk
    )


@pytest.fixture(name="integration")
def integration_fixture(sphere, event):
    return EventIntegration.objects.create(
        event=event,
        kind=IntegrationKind.EXPORT,
        implementation=IntegrationImplementationId.KONWENCIK_SHEET_PUSHER,
        connection=Connection.objects.create(
            sphere=sphere, display_name="Private connection"
        ),
        config_json='{"spreadsheet_id":"private-sheet"}',
    )


def test_read_and_patch_styles(client, token, integration, event):
    track = Track.objects.create(event=event, name="RPG", slug="rpg")
    category = ProposalCategoryFactory(event=event)
    original = KonwencikExportSettings(
        track_colors={track.pk: "#203b50"},
        category_icons={category.pk: "fa.gamepad"},
        photo_url_field_pk=123,
        icon_field_pk=456,
        sync_enabled=True,
        export_lock_time=datetime(2026, 9, 8, tzinfo=UTC),
    )
    integration.settings_json = original.model_dump_json()
    integration.save()

    response = call_org_tool(client, token, "get_konwencik_settings", {})
    assert_response(response, HTTPStatus.OK)
    assert json.loads(tool_text(response)) == [
        {
            "integration_id": integration.pk,
            "context": {
                "tracks": [{"pk": track.pk, "name": "RPG"}],
                "categories": [{"pk": category.pk, "name": category.name}],
                "session_fields": [],
                "settings": original.model_dump(mode="json"),
                "last_run": None,
                "programme_combinations": [],
            },
        }
    ]

    for colors, icons in (
        ({str(track.pk): "#02897e"}, {}),
        ({str(track.pk): ""}, {str(category.pk): ""}),
    ):
        response = call_org_tool(
            client,
            token,
            "update_konwencik_styles",
            {
                "integration_id": integration.pk,
                "track_colors": colors,
                "category_icons": icons,
            },
        )
        assert_response(response, HTTPStatus.OK)
        original.track_colors = {track.pk: "#02897e"} if colors[str(track.pk)] else {}
        if icons:
            original.category_icons = {}
        assert json.loads(tool_text(response)) == original.model_dump(mode="json")
        integration.refresh_from_db()
        assert (
            KonwencikExportSettings.model_validate_json(integration.settings_json)
            == original
        )
        assert integration.config_json == '{"spreadsheet_id":"private-sheet"}'
        assert integration.last_run_json == "{}"


@pytest.mark.parametrize(
    "foreign_kind",
    ("integration", "track", "category", "internal-track", "non-konwencik"),
)
def test_rejects_out_of_scope_ids(client, token, integration, event, foreign_kind):
    other = EventFactory(sphere=event.sphere)
    arguments = {"integration_id": integration.pk}
    if foreign_kind == "integration":
        integration.event = other
        integration.save()
    elif foreign_kind == "non-konwencik":
        integration.implementation = IntegrationImplementationId.GOOGLE_PROPOSAL_PULLER
        integration.save()
    elif foreign_kind == "category":
        category = ProposalCategoryFactory(event=other)
        arguments["category_icons"] = {str(category.pk): "fa.gamepad"}
    else:
        track = Track.objects.create(
            event=event if foreign_kind == "internal-track" else other,
            name="Hidden",
            slug="hidden",
            is_public=foreign_kind != "internal-track",
        )
        arguments["track_colors"] = {str(track.pk): "#203b50"}
    before = integration.settings_json

    response = call_org_tool(client, token, "update_konwencik_styles", arguments)

    assert_response(
        response,
        HTTPStatus.OK,
        content=json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "content": [{"type": "text", "text": "Resource not found"}],
                    "isError": True,
                },
            }
        ).encode(),
    )
    integration.refresh_from_db()
    assert integration.settings_json == before


@pytest.mark.parametrize(
    "patch",
    (
        {"track_colors": {"1": "blue"}},
        {"category_icons": {"1": "x" * 65}},
        {"sync_enabled": True},
        {"event_id": 99},
    ),
)
def test_rejects_invalid_arguments(client, token, integration, patch):
    before = integration.settings_json
    response = call_org_tool(
        client,
        token,
        "update_konwencik_styles",
        {"integration_id": integration.pk, **patch},
    )

    assert_response(response, HTTPStatus.OK)
    result = response.json()["result"]
    assert result["isError"] is True
    assert result["content"][0]["text"].startswith("Invalid arguments:")
    integration.refresh_from_db()
    assert integration.settings_json == before


def test_no_integrations(client, token):
    response = call_org_tool(client, token, "get_konwencik_settings", {})

    assert_response(response, HTTPStatus.OK)
    assert json.loads(tool_text(response)) == []


@pytest.mark.parametrize("sibling_event", (True, False))
def test_read_excludes_other_integrations(client, token, integration, sibling_event):
    if sibling_event:
        integration.event = EventFactory(sphere=integration.event.sphere)
    else:
        integration.implementation = IntegrationImplementationId.GOOGLE_PROPOSAL_PULLER
    integration.save()

    response = call_org_tool(client, token, "get_konwencik_settings", {})

    assert_response(response, HTTPStatus.OK)
    assert json.loads(tool_text(response)) == []
