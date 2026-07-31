from __future__ import annotations

import logging

import pytest
import requests
import responses
from responses import registries

from ludamus.links.ticket_api import MembershipApiClient
from ludamus.pacts import MembershipAPIError


def test_fetch_membership_count_skips_lookup_when_not_configured(settings):
    settings.MEMBERSHIP_API_BASE_URL = ""

    with responses.RequestsMock() as rsps:
        client = MembershipApiClient()

        with pytest.raises(MembershipAPIError):
            client.fetch_membership_count("player@example.com")

        assert not rsps.calls


def test_fetch_membership_count_does_not_log_email_on_success(settings, caplog):
    email = "player@example.com"
    expected_membership_count = 3

    with responses.RequestsMock() as rsps:
        rsps.get(
            settings.MEMBERSHIP_API_BASE_URL,
            json={"membership_count": expected_membership_count},
        )
        client = MembershipApiClient()

        with caplog.at_level(logging.INFO):
            membership_count = client.fetch_membership_count(email)

    assert membership_count == expected_membership_count
    assert email not in caplog.text


def test_fetch_membership_count_does_not_log_email_on_request_exception(
    settings, caplog
):
    email = "player@example.com"

    with responses.RequestsMock(
        registry=registries.OrderedRegistry, assert_all_requests_are_fired=True
    ) as rsps:
        rsps.get(
            settings.MEMBERSHIP_API_BASE_URL, body=requests.RequestException("boom")
        )
        client = MembershipApiClient()

        with caplog.at_level(logging.INFO), pytest.raises(MembershipAPIError):
            client.fetch_membership_count(email)

    assert email not in caplog.text


def test_fetch_membership_count_retries_transient_errors(settings):
    expected_membership_count = 2

    with responses.RequestsMock(
        registry=registries.OrderedRegistry, assert_all_requests_are_fired=True
    ) as rsps:
        rsps.get(settings.MEMBERSHIP_API_BASE_URL, status=503)
        rsps.get(
            settings.MEMBERSHIP_API_BASE_URL,
            json={"membership_count": expected_membership_count},
        )
        client = MembershipApiClient()

        membership_count = client.fetch_membership_count("player@example.com")

    assert membership_count == expected_membership_count


def test_fetch_membership_count_retries_google_style_backend_error(settings):
    expected_membership_count = 4

    with responses.RequestsMock(
        registry=registries.OrderedRegistry, assert_all_requests_are_fired=True
    ) as rsps:
        rsps.get(settings.MEMBERSHIP_API_BASE_URL, status=500)
        rsps.get(
            settings.MEMBERSHIP_API_BASE_URL,
            json={"membership_count": expected_membership_count},
        )
        client = MembershipApiClient()

        membership_count = client.fetch_membership_count("player@example.com")

    assert membership_count == expected_membership_count


def test_fetch_membership_count_fails_when_retries_are_spent(settings):
    with responses.RequestsMock(
        registry=registries.OrderedRegistry, assert_all_requests_are_fired=True
    ) as rsps:
        for _ in range(3):
            rsps.get(settings.MEMBERSHIP_API_BASE_URL, status=503)
        client = MembershipApiClient()

        with pytest.raises(MembershipAPIError):
            client.fetch_membership_count("player@example.com")
