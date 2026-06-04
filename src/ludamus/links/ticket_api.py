"""External API integration for membership lookup."""

from __future__ import annotations

import logging

import requests
from django.conf import settings

from ludamus.pacts import MembershipAPIError

logger = logging.getLogger(__name__)


class MembershipApiClient:
    """Client for external membership API integration."""

    def __init__(self) -> None:
        self.base_url = settings.MEMBERSHIP_API_BASE_URL
        self.token = settings.MEMBERSHIP_API_TOKEN
        self.timeout = settings.MEMBERSHIP_API_TIMEOUT

    def fetch_membership_count(self, email: str) -> int:
        # The membership API is optional: when no base URL is configured there
        # is nothing to look up, so signal "unavailable" without a request.
        if not self.base_url:
            # Global state, identical for every user, so the email adds no
            # diagnostic value here — and keeps it out of the logs.
            logger.debug("Membership API not configured; skipping lookup")
            raise MembershipAPIError

        try:
            response = requests.get(
                self.base_url,
                params={"email": email},
                headers={"Authorization": f"Token {self.token}"},
                timeout=self.timeout,
            )
            response.raise_for_status()

            data = response.json()
            membership_count: int = data.get("membership_count", 0)

            logger.info(
                "Fetched membership count %d for user %s", membership_count, email
            )
        except requests.RequestException as exception:
            logger.exception("Failed to fetch membership for %s", email)
            raise MembershipAPIError from exception
        except Exception as exception:
            logger.exception("Unexpected error fetching membership for %s", email)
            raise MembershipAPIError from exception

        return membership_count
