"""Sklep Kapitularz ticketing integration: membership lookups by email."""

from __future__ import annotations

import logging

import requests
from pydantic import BaseModel, field_validator

from ludamus.links.retry import mount_retries
from ludamus.pacts.chronology import (
    CheckOutcome,
    CheckResult,
    IntegrationKind,
    TicketingIntegrationImplementation,
)
from ludamus.pacts.legacy import MembershipAPIError

logger = logging.getLogger(__name__)

ERROR_HINT_LIMIT = 200
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404
# Nobody's address, so the probe reads a real answer from the shop without
# touching a real customer's record.
PROBE_EMAIL = "integration-check@example.invalid"


class _MembershipResponse(BaseModel):
    # The shop answers with the count of memberships held by that email;
    # a body without the key means "no membership on record".
    membership_count: int = 0


class SklepKapitularzConfig(BaseModel):
    base_url: str
    timeout_seconds: int = 30

    @field_validator("base_url")
    @classmethod
    def check_base_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            message = "base_url must start with http:// or https://"
            raise ValueError(message)
        return value


class SklepKapitularzIntegration(TicketingIntegrationImplementation):
    """Reads a member's ticket count from the Kapitularz shop API.

    The only place that knows this provider's wire format: the connection
    secret travels as a `Token` authorization header, and the answer is the
    `membership_count` key of the JSON body.
    """

    kind: IntegrationKind = IntegrationKind.TICKETING
    config_model: type[BaseModel] = SklepKapitularzConfig

    def check(self, secret: bytes, config: BaseModel) -> CheckResult:
        if not isinstance(config, SklepKapitularzConfig):
            return CheckResult(
                outcome=CheckOutcome.AUTH_FAILED,
                hint="Configuration is not a Sklep Kapitularz config.",
            )
        if not secret:
            return CheckResult(
                outcome=CheckOutcome.AUTH_FAILED, hint="Connection has no secret."
            )
        try:
            response = self._get(secret=secret, config=config, email=PROBE_EMAIL)
        except requests.RequestException as exc:
            return CheckResult(
                outcome=CheckOutcome.NOT_FOUND, hint=f"Request failed: {exc}"
            )
        if response.ok:
            return CheckResult(outcome=CheckOutcome.OK)
        body = (response.text or "")[:ERROR_HINT_LIMIT]
        if response.status_code == HTTP_UNAUTHORIZED:
            return CheckResult(outcome=CheckOutcome.AUTH_FAILED, hint=body)
        if response.status_code == HTTP_FORBIDDEN:
            return CheckResult(
                outcome=CheckOutcome.FORBIDDEN,
                hint=f"Token cannot read memberships: {body}",
            )
        if response.status_code == HTTP_NOT_FOUND:
            return CheckResult(
                outcome=CheckOutcome.NOT_FOUND, hint=f"Endpoint not found: {body}"
            )
        return CheckResult(
            outcome=CheckOutcome.NOT_FOUND,
            hint=f"Unexpected {response.status_code} from the shop: {body}",
        )

    def fetch_membership_count(
        self, *, secret: bytes, config: BaseModel, user_email: str
    ) -> int:
        if not isinstance(config, SklepKapitularzConfig):
            raise MembershipAPIError

        try:
            response = self._get(secret=secret, config=config, email=user_email)
            response.raise_for_status()
            membership_count = _MembershipResponse.model_validate_json(
                response.content
            ).membership_count
        except requests.RequestException as exception:
            logger.exception("Failed to fetch membership")
            raise MembershipAPIError from exception
        except Exception as exception:
            logger.exception("Unexpected error fetching membership")
            raise MembershipAPIError from exception

        logger.info("Fetched membership count %d", membership_count)
        return membership_count

    @staticmethod
    def _get(
        *, secret: bytes, config: SklepKapitularzConfig, email: str
    ) -> requests.Response:
        # A fresh session per call: the resolver builds this client per
        # request, so a pool would never be reused anyway.
        session = mount_retries(requests.Session())
        return session.get(
            config.base_url,
            params={"email": email},
            headers={"Authorization": f"Token {secret.decode()}"},
            timeout=config.timeout_seconds,
        )
