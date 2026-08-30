import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from ludamus.mills.integrations import (
    EventIntegrationsService,
    IntegrationImplementationNotFoundError,
    IntegrationImplementations,
)
from ludamus.pacts import MembershipAPIError, NotFoundError
from ludamus.pacts.chronology import (
    CheckOutcome,
    CheckResult,
    EventIntegrationCreateData,
    IntegrationCheckRequest,
    IntegrationImplementationId,
    IntegrationKind,
    SourceQuestion,
)
from ludamus.pacts.multiverse import DecryptionError
from ludamus.pacts.submissions import ImportSettings


class _StrictConfig(BaseModel):
    endpoint: str


class _ImportStubImpl:
    kind = IntegrationKind.IMPORT
    config_model = _StrictConfig

    def check(self, secret, config):
        return CheckResult(outcome=CheckOutcome.OK, hint="")


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


class _ExportStubImpl:
    kind = IntegrationKind.EXPORT
    config_model = _StrictConfig

    def check(self, secret, config):
        return CheckResult(outcome=CheckOutcome.OK, hint="")


class _TicketingStubImpl:
    kind = IntegrationKind.TICKETING
    config_model = BaseModel

    def check(self, secret, config):
        return CheckResult(outcome=CheckOutcome.OK, hint="")


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


def _create_data():
    return EventIntegrationCreateData(
        kind=IntegrationKind.IMPORT,
        implementation=_IMPL,
        connection_id=3,
        display_name="x",
        config_json="{}",
    )


class TestEventIntegrationsServiceCheck:
    def test_unknown_implementation_returns_not_found(self):
        env = _make_service()

        result = env.svc.check(
            IntegrationCheckRequest(
                sphere_id=1, implementation=_IMPL, connection_id=2, config_json="{}"
            )
        )

        assert result.outcome == CheckOutcome.NOT_FOUND
        assert _IMPL.value in result.hint
        # Short-circuits before touching the connection secret or decryptor.
        env.connections.read_secret.assert_not_called()
        env.decryptor.decrypt.assert_not_called()

    def test_invalid_config_returns_not_found(self):
        env = _make_service(imports={_IMPL: _ImportStubImpl()})

        result = env.svc.check(
            IntegrationCheckRequest(
                sphere_id=1,
                implementation=_IMPL,
                connection_id=2,
                # endpoint must be a string; a JSON number trips ValidationError.
                config_json='{"endpoint": 123}',
            )
        )

        assert result.outcome == CheckOutcome.NOT_FOUND
        assert "Invalid config" in result.hint
        # ValidationError funnels out before reading the secret.
        env.connections.read_secret.assert_not_called()
        env.decryptor.decrypt.assert_not_called()

    def test_missing_connection_returns_not_found(self):
        env = _make_service(imports={_IMPL: _ImportStubImpl()})
        env.connections.read_secret.side_effect = NotFoundError

        result = env.svc.check(
            IntegrationCheckRequest(
                sphere_id=1,
                implementation=_IMPL,
                connection_id=999,
                config_json='{"endpoint": "x"}',
            )
        )

        assert result.outcome == CheckOutcome.NOT_FOUND
        assert result.hint == "Connection not found."
        # A NotFoundError becomes a graceful result; nothing gets decrypted.
        env.decryptor.decrypt.assert_not_called()


class TestEventIntegrationsServiceRequireImplementation:
    def test_create_with_unknown_implementation_raises(self):
        env = _make_service()

        with pytest.raises(IntegrationImplementationNotFoundError):
            env.svc.create(sphere_id=1, event_id=2, data=_create_data())

        # Guard raises before any IO or transaction.
        env.connections.get.assert_not_called()
        env.transaction.atomic.assert_not_called()
        env.integrations.create.assert_not_called()

    def test_create_with_wrong_kind_raises(self):
        env = _make_service(ticketing={_IMPL: _TicketingStubImpl()})

        with pytest.raises(IntegrationImplementationNotFoundError):
            env.svc.create(sphere_id=1, event_id=2, data=_create_data())

        env.connections.get.assert_not_called()
        env.transaction.atomic.assert_not_called()
        env.integrations.create.assert_not_called()


class TestEventIntegrationsServiceSnapshotAndFetch:
    def test_fetch_questions_returns_empty_when_implementation_missing(self):
        env = _make_service()
        env.integrations.get.return_value = MagicMock(implementation=_IMPL)

        result = env.svc.fetch_questions(sphere_id=1, event_id=2, pk=3)

        assert result == []
        # No registered impl: short-circuits before touching the secret.
        env.connections.read_secret.assert_not_called()
        env.decryptor.decrypt.assert_not_called()

    def test_fetch_responses_returns_empty_when_implementation_missing(self):
        env = _make_service()
        env.integrations.get.return_value = MagicMock(implementation=_IMPL)

        result = env.svc.fetch_responses(sphere_id=1, event_id=2, pk=3)

        assert result == []
        env.connections.read_secret.assert_not_called()
        env.decryptor.decrypt.assert_not_called()

    def test_fetch_headers_returns_empty_when_implementation_missing(self):
        env = _make_service()
        env.integrations.get.return_value = MagicMock(implementation=_IMPL)

        result = env.svc.fetch_headers(sphere_id=1, event_id=2, pk=3)

        assert result == []
        env.connections.read_secret.assert_not_called()
        env.decryptor.decrypt.assert_not_called()

    def test_fetch_questions_returns_empty_for_a_registered_non_source(self):
        # An exporter is in the registry (so it can be created and checked) but
        # not among the import implementations, and has no `fetch_*` to call.
        env = _make_service(exports={_IMPL: _ExportStubImpl()})
        env.integrations.get.return_value = MagicMock(implementation=_IMPL)

        assert env.svc.fetch_questions(sphere_id=1, event_id=2, pk=3) == []
        env.connections.read_secret.assert_not_called()

    def test_populate_snapshot_caches_the_sheet_header_row(self):
        # The header row is what the run tab offers as unique-key columns, so it
        # must include the metadata columns the form schema never carries.
        headers = ["Sygnatura czasowa", "Adres e-mail", "Tytuł"]
        event_id, pk = 2, 3
        impl = _HeaderStubImpl(headers=headers)
        env = _make_service(imports={_IMPL: impl})
        env.integrations.get.return_value = MagicMock(
            implementation=_IMPL, config_json='{"endpoint": "x"}', settings_json="{}"
        )

        env.svc.populate_questions_snapshot(sphere_id=1, event_id=event_id, pk=pk)

        saved = env.integrations.update_settings.call_args.kwargs
        assert saved["event_id"] == event_id
        assert saved["pk"] == pk
        assert (
            ImportSettings.model_validate_json(saved["settings_json"]).sheet_headers
            == headers
        )

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

    def test_get_cached_questions_returns_empty_on_invalid_snapshot_json(self):
        env = _make_service()
        env.integrations.get.return_value = MagicMock(
            questions_snapshot_json="not valid json"
        )

        assert env.svc.get_cached_questions(2, 3) == []


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
    def test_resolve_binds_the_decrypted_secret_to_the_implementation(self):
        env = _ticketing_env([_ticketing_row()])

        client = env.svc.resolve(event_id=7, sphere_id=1)

        assert client.fetch_membership_count(_EMAIL) == _MEMBERSHIP_COUNT
        assert env.impl.seen == [(b"token", "https://shop.example.com", _EMAIL)]

    def test_resolve_falls_back_to_the_next_usable_integration(self):
        # First usable row wins; a broken one must not take the event down.
        env = _ticketing_env(
            [_ticketing_row(pk=1, config_json='{"base_url": 42}'), _ticketing_row(pk=2)]
        )

        client = env.svc.resolve(event_id=7, sphere_id=1)

        assert client.fetch_membership_count(_EMAIL) == _MEMBERSHIP_COUNT

    def test_resolve_without_an_integration_raises_membership_api_error(self):
        env = _ticketing_env([])

        client = env.svc.resolve(event_id=7, sphere_id=1)

        with pytest.raises(MembershipAPIError):
            client.fetch_membership_count(_EMAIL)

    def test_resolve_skips_an_unknown_implementation(self):
        env = _ticketing_env([])
        env.integrations.list_for_event.return_value = [
            SimpleNamespace(
                pk=1,
                implementation=IntegrationImplementationId.GOOGLE_PROPOSAL_PULLER,
                connection_id=3,
                config_json="{}",
            )
        ]

        with pytest.raises(MembershipAPIError):
            env.svc.resolve(event_id=7, sphere_id=1).fetch_membership_count(_EMAIL)

    def test_resolve_skips_a_missing_connection(self):
        env = _ticketing_env([_ticketing_row()])
        env.connections.read_secret.side_effect = NotFoundError

        with pytest.raises(MembershipAPIError):
            env.svc.resolve(event_id=7, sphere_id=1).fetch_membership_count(_EMAIL)

    def test_resolve_logs_a_connection_without_a_secret(self, caplog):
        env = _ticketing_env([_ticketing_row()])
        env.connections.read_secret.return_value = b""

        with caplog.at_level(logging.WARNING):
            client = env.svc.resolve(event_id=7, sphere_id=1)

        assert "no secret" in caplog.text
        with pytest.raises(MembershipAPIError):
            client.fetch_membership_count(_EMAIL)

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

    def test_resolve_reads_the_integration_rows_once_per_event(self):
        env = _ticketing_env([_ticketing_row()])

        env.svc.resolve(event_id=7, sphere_id=1)
        env.svc.resolve(event_id=7, sphere_id=1)

        env.integrations.list_for_event.assert_called_once_with(
            7, IntegrationKind.TICKETING
        )
