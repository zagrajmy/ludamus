from __future__ import annotations

from unittest.mock import patch

import pytest

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
