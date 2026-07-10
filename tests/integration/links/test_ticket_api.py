from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest
import requests

from ludamus.links.ticket_api import MembershipApiClient
from ludamus.pacts import MembershipAPIError


def test_fetch_membership_count_skips_lookup_when_not_configured(settings):
    settings.MEMBERSHIP_API_BASE_URL = ""
    client = MembershipApiClient()

    with (
        patch("ludamus.links.ticket_api.requests.get") as mock_get,
        pytest.raises(MembershipAPIError),
    ):
        client.fetch_membership_count("player@example.com")

    mock_get.assert_not_called()


def test_fetch_membership_count_does_not_log_email_on_success(caplog):
    email = "player@example.com"
    expected_membership_count = 3
    client = MembershipApiClient()
    mock_response = MagicMock()
    mock_response.json.return_value = {"membership_count": expected_membership_count}

    with (
        patch("ludamus.links.ticket_api.requests.get", return_value=mock_response),
        caplog.at_level(logging.INFO),
    ):
        membership_count = client.fetch_membership_count(email)

    assert membership_count == expected_membership_count
    assert email not in caplog.text


def test_fetch_membership_count_does_not_log_email_on_request_exception(caplog):
    email = "player@example.com"
    client = MembershipApiClient()

    with (
        patch(
            "ludamus.links.ticket_api.requests.get",
            side_effect=requests.RequestException,
        ),
        caplog.at_level(logging.INFO),
        pytest.raises(MembershipAPIError),
    ):
        client.fetch_membership_count(email)

    assert email not in caplog.text
