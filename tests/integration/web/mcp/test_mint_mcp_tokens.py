from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from tests.integration.conftest import EventFactory, SphereFactory, UserFactory
from tests.integration.web.mcp.test_mcp_endpoint import post_message
from tests.integration.web.mcp.test_mcp_organizer_endpoint import post_org

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "scripts" / "mint_mcp_tokens.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("mint_mcp_tokens", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(name="mint")
def mint_fixture():
    return _load_script()


class TestMintMcpTokens:
    def test_writes_tokens_that_authenticate(
        self, mint, client, tmp_path: Path
    ) -> None:
        sphere = SphereFactory()
        admin = UserFactory(username="admin", is_superuser=True)
        manager = UserFactory(username="e2e-manager", is_staff=True)
        sphere.managers.add(manager)
        event = EventFactory(slug="autumn-open", sphere=sphere)
        EventFactory(slug="sunhaven-festival", sphere=sphere)

        output = tmp_path / "mcp-tokens.json"
        payload = mint.build_payload()
        mint.write_payload(payload=payload, output=output)

        assert output.exists()
        maintainer = payload["maintainer"]
        assert maintainer["username"] == "admin"
        assert maintainer["user_id"] == admin.pk
        organizer = payload["organizer"]
        assert set(organizer) == {"autumn-open", "sunhaven-festival"}
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

    def test_falls_back_to_any_superuser_and_only_event(
        self, mint, tmp_path: Path
    ) -> None:
        sphere = SphereFactory()
        importer = UserFactory(username="local-mcp-importer", is_superuser=True)
        event = EventFactory(slug="polcon-2026", sphere=sphere)

        payload = mint.build_payload()
        mint.write_payload(payload=payload, output=tmp_path / "tokens.json")

        assert payload["maintainer"]["username"] == "local-mcp-importer"
        assert payload["maintainer"]["user_id"] == importer.pk
        organizer = payload["organizer"]
        assert list(organizer) == ["polcon-2026"]
        assert organizer["polcon-2026"]["username"] == "local-mcp-importer"
        assert organizer["polcon-2026"]["event_id"] == event.pk

    def test_fails_without_a_superuser(self, mint) -> None:
        with pytest.raises(SystemExit, match="No active superuser"):
            mint.build_payload()
