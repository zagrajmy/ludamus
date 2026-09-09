"""Integration tests for the export_konwencik management command.

`google.auth` is mocked at the package boundary; the real sweep, the real
repositories and the real `GoogleSheetsWriter` run against the fake session.
"""

from __future__ import annotations

import json
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from django.conf import settings as django_settings
from django.core.management import call_command

from ludamus.links.db.django.models import Connection, EventIntegration
from ludamus.links.encryption import FernetEncryptor
from ludamus.pacts.chronology import IntegrationImplementationId, IntegrationKind
from ludamus.pacts.konwencik import KonwencikExportSettings
from tests.integration.conftest import AgendaItemFactory, SessionFactory

CONFIG_JSON = json.dumps({"spreadsheet_id": "sheet-1", "tab": "harmonogram"})
_HEADER_ROWS = 2  # machine keys, then Konwencik's own labels


def _google_session() -> MagicMock:
    def get(url: str, **_kwargs: object) -> MagicMock:
        if "/values/" in url:
            return MagicMock(ok=True, json=lambda: {"values": []})
        return MagicMock(
            ok=True, json=lambda: {"sheets": [{"properties": {"title": "harmonogram"}}]}
        )

    session = MagicMock()
    session.get.side_effect = get
    session.put.return_value = MagicMock(ok=True, status_code=200, text="")
    return session


@pytest.fixture(name="google")
def google_fixture():
    session = _google_session()
    with (
        patch("ludamus.links.google_auth.Credentials.from_service_account_info"),
        patch("ludamus.links.google_auth.AuthorizedSession") as session_cls,
    ):
        session_cls.return_value = session
        yield session


def _integration(event, *, sync_enabled: bool) -> EventIntegration:
    blob = FernetEncryptor(django_settings.CREDENTIALS_ENCRYPTION_KEY).encrypt(
        json.dumps({"type": "service_account"}).encode()
    )
    return EventIntegration.objects.create(
        event=event,
        kind=IntegrationKind.EXPORT.value,
        implementation=IntegrationImplementationId.KONWENCIK_SHEET_PUSHER.value,
        connection=Connection.objects.create(
            sphere=event.sphere, display_name="API Key A", secret=blob
        ),
        display_name="Konwencik",
        config_json=CONFIG_JSON,
        settings_json=KonwencikExportSettings(
            sync_enabled=sync_enabled
        ).model_dump_json(),
    )


@pytest.mark.django_db
class TestExportKonwencik:
    def test_exports_every_sync_enabled_integration(self, event, google):
        _integration(event, sync_enabled=True)
        session = SessionFactory(category__event=event, event=event)
        AgendaItemFactory(session=session, space__event=event)
        out = StringIO()

        call_command("export_konwencik", stdout=out)

        assert "Exported 1 integration(s) to Konwencik." in out.getvalue()
        written = google.put.call_args.kwargs["json"]["values"]
        assert len(written) == _HEADER_ROWS + 1

    def test_leaves_an_integration_with_sync_off_alone(self, event, google):
        _integration(event, sync_enabled=False)
        out = StringIO()

        call_command("export_konwencik", stdout=out)

        assert "Exported 0 integration(s) to Konwencik." in out.getvalue()
        google.put.assert_not_called()
