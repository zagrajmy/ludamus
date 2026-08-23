from __future__ import annotations

import json
import logging

import pytest
import requests
import responses
from django.conf import settings
from responses import registries

from ludamus.links.encryption import FernetDecryptor, FernetEncryptor
from ludamus.links.sklep_kapitularz import (
    SklepKapitularzConfig,
    SklepKapitularzIntegration,
)
from ludamus.links.ticket_api import TicketApiResolver
from ludamus.pacts import MembershipAPIError
from ludamus.pacts.chronology import (
    CheckOutcome,
    EventIntegrationDTO,
    IntegrationImplementationId,
    IntegrationKind,
)

BASE_URL = "https://membership-test.example.com/api/v1/endpoint"
TOKEN = "membership-test-token"
SECRET = TOKEN.encode()
RESOLVED_MEMBERSHIP_COUNT = 5


@pytest.fixture(name="config")
def config_fixture():
    return SklepKapitularzConfig(base_url=BASE_URL)


@pytest.fixture(name="integration")
def integration_fixture():
    return SklepKapitularzIntegration()


def test_config_rejects_a_base_url_without_a_scheme():
    with pytest.raises(ValueError, match="http"):
        SklepKapitularzConfig(base_url="membership.example.com")


def test_fetch_membership_count_sends_the_token_and_reads_the_count(
    integration, config
):
    expected_membership_count = 3

    with responses.RequestsMock() as rsps:
        rsps.get(BASE_URL, json={"membership_count": expected_membership_count})

        membership_count = integration.fetch_membership_count(
            secret=SECRET, config=config, user_email="player@example.com"
        )

        assert rsps.calls[0].request.headers["Authorization"] == f"Token {TOKEN}"
        assert rsps.calls[0].request.params == {"email": "player@example.com"}

    assert membership_count == expected_membership_count


def test_fetch_membership_count_reads_zero_when_the_key_is_absent(integration, config):
    with responses.RequestsMock() as rsps:
        rsps.get(BASE_URL, json={})

        assert (
            integration.fetch_membership_count(
                secret=SECRET, config=config, user_email="player@example.com"
            )
            == 0
        )


def test_fetch_membership_count_does_not_log_email_on_success(
    integration, config, caplog
):
    email = "player@example.com"

    with responses.RequestsMock() as rsps:
        rsps.get(BASE_URL, json={"membership_count": 3})

        with caplog.at_level(logging.INFO):
            integration.fetch_membership_count(
                secret=SECRET, config=config, user_email=email
            )

    assert email not in caplog.text


def test_fetch_membership_count_does_not_log_email_on_request_exception(
    integration, config, caplog
):
    email = "player@example.com"

    with responses.RequestsMock(
        registry=registries.OrderedRegistry, assert_all_requests_are_fired=True
    ) as rsps:
        rsps.get(BASE_URL, body=requests.RequestException("boom"))

        with caplog.at_level(logging.INFO), pytest.raises(MembershipAPIError):
            integration.fetch_membership_count(
                secret=SECRET, config=config, user_email=email
            )

    assert email not in caplog.text


def test_fetch_membership_count_retries_transient_errors(integration, config):
    expected_membership_count = 2

    with responses.RequestsMock(
        registry=registries.OrderedRegistry, assert_all_requests_are_fired=True
    ) as rsps:
        rsps.get(BASE_URL, status=503)
        rsps.get(BASE_URL, json={"membership_count": expected_membership_count})

        membership_count = integration.fetch_membership_count(
            secret=SECRET, config=config, user_email="player@example.com"
        )

    assert membership_count == expected_membership_count


def test_fetch_membership_count_retries_server_errors(integration, config):
    expected_membership_count = 4

    with responses.RequestsMock(
        registry=registries.OrderedRegistry, assert_all_requests_are_fired=True
    ) as rsps:
        rsps.get(BASE_URL, status=500)
        rsps.get(BASE_URL, json={"membership_count": expected_membership_count})

        membership_count = integration.fetch_membership_count(
            secret=SECRET, config=config, user_email="player@example.com"
        )

    assert membership_count == expected_membership_count


def test_fetch_membership_count_fails_when_retries_are_spent(integration, config):
    with responses.RequestsMock(
        registry=registries.OrderedRegistry, assert_all_requests_are_fired=True
    ) as rsps:
        for _ in range(3):
            rsps.get(BASE_URL, status=503)

        with pytest.raises(MembershipAPIError):
            integration.fetch_membership_count(
                secret=SECRET, config=config, user_email="player@example.com"
            )


def test_check_reports_ok(integration, config):
    with responses.RequestsMock() as rsps:
        rsps.get(BASE_URL, json={"membership_count": 0})

        assert integration.check(SECRET, config).outcome == CheckOutcome.OK


def test_check_reports_a_missing_secret(integration, config):
    with responses.RequestsMock() as rsps:
        result = integration.check(b"", config)

        assert not rsps.calls

    assert result.outcome == CheckOutcome.AUTH_FAILED


@pytest.mark.parametrize(
    ("status", "expected_outcome"),
    (
        (401, CheckOutcome.AUTH_FAILED),
        (403, CheckOutcome.FORBIDDEN),
        (404, CheckOutcome.NOT_FOUND),
        (418, CheckOutcome.NOT_FOUND),
    ),
)
def test_check_maps_error_statuses(integration, config, status, expected_outcome):
    with responses.RequestsMock() as rsps:
        rsps.get(BASE_URL, status=status)

        assert integration.check(SECRET, config).outcome == expected_outcome


def test_check_reports_a_failed_request(integration, config):
    with responses.RequestsMock() as rsps:
        rsps.get(BASE_URL, body=requests.RequestException("boom"))

        assert integration.check(SECRET, config).outcome == CheckOutcome.NOT_FOUND


class FakeIntegrationsRepository:
    def __init__(self, integrations: list[EventIntegrationDTO]) -> None:
        self._integrations = integrations
        self.calls = 0

    def list_for_event(
        self, event_id: int, kind: IntegrationKind | None = None
    ) -> list[EventIntegrationDTO]:
        self.calls += 1
        return [
            integration
            for integration in self._integrations
            if integration.event_id == event_id
            and (kind is None or integration.kind == kind)
        ]


class FakeConnectionsRepository:
    def __init__(self, secrets: dict[int, bytes]) -> None:
        self._secrets = secrets

    def read_secret(self, _sphere_id: int, pk: int) -> bytes:
        return self._secrets[pk]


def make_dto(**overrides) -> EventIntegrationDTO:
    return EventIntegrationDTO(
        **{
            "pk": 1,
            "event_id": 7,
            "kind": IntegrationKind.TICKETING,
            "implementation": IntegrationImplementationId.SKLEP_KAPITULARZ,
            "connection_id": 3,
            "connection_display_name": "Shop token",
            "display_name": "Kapitularz",
            "config_json": json.dumps({"base_url": BASE_URL}),
            "settings_json": "{}",
            **overrides,
        }
    )


def encrypted_secret() -> bytes:
    return FernetEncryptor(settings.CREDENTIALS_ENCRYPTION_KEY).encrypt(SECRET)


def make_resolver(dtos, *, secrets=None, repository=None) -> TicketApiResolver:
    return TicketApiResolver(
        repository or FakeIntegrationsRepository(dtos),
        FakeConnectionsRepository(
            {3: encrypted_secret()} if secrets is None else secrets
        ),
        FernetDecryptor(settings.CREDENTIALS_ENCRYPTION_KEY),
        {IntegrationImplementationId.SKLEP_KAPITULARZ: SklepKapitularzIntegration()},
    )


def test_resolver_returns_a_client_that_calls_the_configured_shop():
    resolver = make_resolver([make_dto()])

    client = resolver.resolve(event_id=7, sphere_id=1)

    assert client is not None
    with responses.RequestsMock() as rsps:
        rsps.get(BASE_URL, json={"membership_count": RESOLVED_MEMBERSHIP_COUNT})

        assert (
            client.fetch_membership_count("player@example.com")
            == RESOLVED_MEMBERSHIP_COUNT
        )


def test_resolver_returns_none_without_a_ticketing_integration():
    assert make_resolver([]).resolve(event_id=7, sphere_id=1) is None


def test_resolver_skips_an_unknown_implementation():
    dto = make_dto(implementation=IntegrationImplementationId.GOOGLE_PROPOSAL_PULLER)

    assert make_resolver([dto]).resolve(event_id=7, sphere_id=1) is None


def test_resolver_skips_an_unparseable_config():
    dto = make_dto(config_json=json.dumps({"base_url": "not-a-url"}))

    assert make_resolver([dto]).resolve(event_id=7, sphere_id=1) is None


def test_resolver_skips_a_connection_without_a_secret():
    resolver = make_resolver([make_dto()], secrets={3: b""})

    assert resolver.resolve(event_id=7, sphere_id=1) is None


def test_resolver_reads_the_integration_row_once_per_event():
    repository = FakeIntegrationsRepository([make_dto()])
    resolver = make_resolver([], repository=repository)

    resolver.resolve(event_id=7, sphere_id=1)
    resolver.resolve(event_id=7, sphere_id=1)

    assert repository.calls == 1
