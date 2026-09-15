from __future__ import annotations

import pytest

from scripts.mcp_token_file import load_token_file, parse_token_file
from scripts.mint_mcp_tokens import build_payload, write_token_file
from tests.integration.conftest import EventFactory, SphereFactory, UserFactory
from tests.integration.web.mcp.test_mcp_endpoint import post_message
from tests.integration.web.mcp.test_mcp_organizer_endpoint import post_org


class TestMintMcpTokens:
    def test_writes_tokens_that_authenticate(self, client, tmp_path) -> None:
        sphere = SphereFactory()
        admin = UserFactory(username="admin", is_superuser=True)
        manager = UserFactory(username="e2e-manager", is_staff=True)
        sphere.managers.add(manager)
        event = EventFactory(slug="autumn-open", sphere=sphere)
        EventFactory(slug="sunhaven-festival", sphere=sphere)
        EventFactory(slug="enroll-states", sphere=sphere)

        output = tmp_path / "mcp-tokens.json"
        payload = build_payload()
        write_token_file(payload=payload, output=output)

        assert output.exists()
        maintainer = payload["maintainer"]
        assert maintainer["username"] == "admin"
        assert maintainer["user_id"] == admin.pk
        organizer = payload["organizer"]
        assert set(organizer) == {"autumn-open", "sunhaven-festival", "enroll-states"}
        autumn = organizer["autumn-open"]
        assert autumn["username"] == "e2e-manager"
        assert autumn["user_id"] == manager.pk
        assert autumn["event_id"] == event.pk
        assert autumn["sphere_id"] == sphere.pk

        ping = post_message(
            client,
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            token=maintainer["token"],
        )
        assert ping.json() == {"jsonrpc": "2.0", "id": 1, "result": {}}

        org_ping = post_org(
            client, {"jsonrpc": "2.0", "id": 1, "method": "ping"}, token=autumn["token"]
        )
        assert org_ping.json() == {"jsonrpc": "2.0", "id": 1, "result": {}}

    def test_falls_back_to_any_superuser_and_only_event(self, tmp_path) -> None:
        sphere = SphereFactory()
        importer = UserFactory(username="local-mcp-importer", is_superuser=True)
        event = EventFactory(slug="polcon-2026", sphere=sphere)

        payload = build_payload()
        write_token_file(payload=payload, output=tmp_path / "tokens.json")

        assert payload["maintainer"]["username"] == "local-mcp-importer"
        assert payload["maintainer"]["user_id"] == importer.pk
        organizer = payload["organizer"]
        assert list(organizer) == ["polcon-2026"]
        assert organizer["polcon-2026"]["username"] == "local-mcp-importer"
        assert organizer["polcon-2026"]["event_id"] == event.pk

    def test_fails_without_a_superuser(self) -> None:
        with pytest.raises(SystemExit, match="No active superuser"):
            build_payload()

    def test_event_flag_mints_one_slug(self) -> None:
        sphere = SphereFactory()
        UserFactory(username="admin", is_superuser=True)
        EventFactory(slug="autumn-open", sphere=sphere)
        EventFactory(slug="enroll-states", sphere=sphere)

        payload = build_payload(event_slug="enroll-states")

        assert list(payload["organizer"]) == ["enroll-states"]

    def test_unknown_event_slug_fails(self) -> None:
        UserFactory(username="admin", is_superuser=True)
        with pytest.raises(SystemExit, match="No event with slug"):
            build_payload(event_slug="missing-event")


class TestMcpTokenFile:
    def test_roundtrip_and_reject_bad_version(self, tmp_path) -> None:
        sphere = SphereFactory()
        UserFactory(username="admin", is_superuser=True)
        EventFactory(slug="autumn-open", sphere=sphere)
        output = tmp_path / "tokens.json"
        payload = build_payload()
        write_token_file(payload=payload, output=output)

        loaded = load_token_file(output)
        assert loaded is not None
        assert loaded["version"] == 1
        assert loaded["maintainer"]["token"] == payload["maintainer"]["token"]
        assert set(loaded["organizer"]) == {"autumn-open"}

        with pytest.raises(ValueError, match="version must be 1"):
            parse_token_file({**loaded, "version": 2})

        with pytest.raises(TypeError, match="must be an object"):
            parse_token_file("nope")
