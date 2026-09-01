from __future__ import annotations

import logging

import pytest
import requests
import responses
from responses import registries

from ludamus.links.google_forms import GoogleDocsProposalConfig
from ludamus.links.sklep_kapitularz import (
    SklepKapitularzConfig,
    SklepKapitularzIntegration,
)
from ludamus.pacts import MembershipAPIError
from ludamus.pacts.chronology import CheckOutcome

BASE_URL = "https://membership-test.example.com/api/v1/endpoint"
TOKEN = "membership-test-token"
SECRET = TOKEN.encode()
# Another implementation's config, the shape the guards are there to refuse.
OTHER_CONFIG = GoogleDocsProposalConfig(sheet_id="sheet", form_id="form")


@pytest.fixture(name="config")
def config_fixture():
    return SklepKapitularzConfig(base_url=BASE_URL)


@pytest.fixture(name="integration")
def integration_fixture():
    return SklepKapitularzIntegration()


@pytest.mark.parametrize(
    "base_url", ("membership.example.com", "http://membership.example.com/api")
)
def test_config_rejects_a_base_url_without_a_scheme(base_url):
    with pytest.raises(ValueError, match="https"):
        SklepKapitularzConfig(base_url=base_url)


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
        (418, CheckOutcome.AUTH_FAILED),
    ),
)
def test_check_maps_error_statuses(integration, config, status, expected_outcome):
    with responses.RequestsMock() as rsps:
        rsps.get(BASE_URL, status=status)

        assert integration.check(SECRET, config).outcome == expected_outcome


def test_check_reports_a_failed_request(integration, config):
    with responses.RequestsMock() as rsps:
        rsps.get(BASE_URL, body=requests.RequestException("boom"))

        assert integration.check(SECRET, config).outcome == CheckOutcome.AUTH_FAILED


def test_check_rejects_a_body_without_a_membership_count(integration, config):
    with responses.RequestsMock() as rsps:
        rsps.get(BASE_URL, body="<html>Zaloguj się</html>", content_type="text/html")

        result = integration.check(SECRET, config)

    assert result.outcome == CheckOutcome.NOT_FOUND
    assert "did not answer with a count" in result.hint


def test_check_rejects_a_config_from_another_implementation(integration):
    with responses.RequestsMock() as rsps:
        result = integration.check(SECRET, OTHER_CONFIG)

        assert not rsps.calls

    assert result.outcome == CheckOutcome.AUTH_FAILED
    assert "not a Sklep Kapitularz config" in result.hint


def test_fetch_membership_count_rejects_a_config_from_another_implementation(
    integration,
):
    with responses.RequestsMock() as rsps:
        with pytest.raises(MembershipAPIError):
            integration.fetch_membership_count(
                secret=SECRET, config=OTHER_CONFIG, user_email="player@example.com"
            )

        assert not rsps.calls
