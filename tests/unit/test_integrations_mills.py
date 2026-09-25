import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from ludamus.mills.integrations import (
    EventIntegrationsService,
    IntegrationImplementations,
)
from ludamus.pacts import MembershipAPIError
from ludamus.pacts.chronology import (
    CheckOutcome,
    CheckResult,
    IntegrationImplementationId,
    IntegrationKind,
    SourceQuestion,
)
from ludamus.pacts.multiverse import DecryptionError


class _StrictConfig(BaseModel):
    endpoint: str


class _HeaderStubImpl:
    kind = IntegrationKind.IMPORT
    config_model = _StrictConfig

    def __init__(self, headers):
        self._headers = headers

    def check(self, secret, config):
        return CheckResult(outcome=CheckOutcome.OK, hint="")

    def fetch_questions(self, **_kwargs):
        return [SourceQuestion(title="Tytuł")]

    def fetch_headers(self, **_kwargs):
        return self._headers


_IMPL = IntegrationImplementationId.GOOGLE_PROPOSAL_PULLER


def _make_service(*, imports=None, ticketing=None, exports=None):
    transaction = MagicMock()
    transaction.atomic.return_value.__enter__ = MagicMock(return_value=None)
    transaction.atomic.return_value.__exit__ = MagicMock(return_value=None)
    integrations = MagicMock()
    connections = MagicMock()
    decryptor = MagicMock()
    svc = EventIntegrationsService(
        transaction=transaction,
        integrations=integrations,
        connections=connections,
        decryptor=decryptor,
        implementations=IntegrationImplementations(
            imports=imports or {}, ticketing=ticketing or {}, exports=exports or {}
        ),
    )
    return SimpleNamespace(
        svc=svc,
        transaction=transaction,
        integrations=integrations,
        connections=connections,
        decryptor=decryptor,
    )


class TestEventIntegrationsServiceSnapshotAndFetch:
    def test_populate_snapshot_keeps_cached_headers_when_the_fetch_fails(self):
        # A transient Sheets failure yields []; wiping the cache would empty the
        # unique-key select the operator already configured against.
        env = _make_service(imports={_IMPL: _HeaderStubImpl(headers=[])})
        env.integrations.get.return_value = MagicMock(
            implementation=_IMPL,
            config_json='{"endpoint": "x"}',
            settings_json='{"sheet_headers": ["Sygnatura czasowa"]}',
        )

        env.svc.populate_questions_snapshot(sphere_id=1, event_id=2, pk=3)

        env.integrations.update_settings.assert_not_called()
        env.integrations.update_questions_snapshot.assert_called_once()


class _MembershipConfig(BaseModel):
    base_url: str


class _TicketingFetchImpl:
    kind = IntegrationKind.TICKETING
    config_model = _MembershipConfig

    def __init__(self, membership_count):
        self.seen = []
        self._membership_count = membership_count

    def check(self, secret, config):
        return CheckResult(outcome=CheckOutcome.OK, hint="")

    def fetch_membership_count(self, *, secret, config, user_email):
        self.seen.append((secret, config.base_url, user_email))
        return self._membership_count


_TICKET_IMPL = IntegrationImplementationId.SKLEP_KAPITULARZ
_MEMBERSHIP_COUNT = 5
_EMAIL = "player@example.com"


def _ticketing_row(pk=1, config_json='{"base_url": "https://shop.example.com"}'):
    return SimpleNamespace(
        pk=pk, implementation=_TICKET_IMPL, connection_id=3, config_json=config_json
    )


def _ticketing_env(rows, *, membership_count=_MEMBERSHIP_COUNT):
    impl = _TicketingFetchImpl(membership_count=membership_count)
    env = _make_service(ticketing={_TICKET_IMPL: impl})
    env.integrations.list_for_event.return_value = rows
    env.connections.read_secret.return_value = b"blob"
    env.decryptor.decrypt.return_value = b"token"
    env.impl = impl
    return env


class TestEventIntegrationsServiceTicketApi:
    def test_resolve_falls_back_to_the_next_usable_integration(self):
        # First usable row wins; a broken one must not take the event down.
        env = _ticketing_env(
            [_ticketing_row(pk=1, config_json='{"base_url": 42}'), _ticketing_row(pk=2)]
        )

        client = env.svc.resolve(event_id=7, sphere_id=1)

        assert client.fetch_membership_count(_EMAIL) == _MEMBERSHIP_COUNT

    def test_resolve_logs_a_secret_that_does_not_decrypt(self, caplog):
        # A rotated key or a truncated column must skip the row, not 500 the
        # enrollment page it was resolved for.
        env = _ticketing_env([_ticketing_row()])
        env.decryptor.decrypt.side_effect = DecryptionError

        with caplog.at_level(logging.WARNING):
            client = env.svc.resolve(event_id=7, sphere_id=1)

        assert "does not decrypt" in caplog.text
        with pytest.raises(MembershipAPIError):
            client.fetch_membership_count(_EMAIL)
