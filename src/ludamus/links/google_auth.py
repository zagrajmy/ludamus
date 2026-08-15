"""Service-account session building and probing, shared by the Google links."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Protocol

import requests
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.service_account import Credentials

from ludamus.links.retry import mount_retries
from ludamus.pacts.chronology import CheckOutcome, CheckResult

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence


class _CredentialsFactory(Protocol):
    def __call__(
        self, info: Mapping[str, object], *, scopes: list[str]
    ) -> Credentials: ...


ERROR_HINT_LIMIT = 200
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404


class CredentialsError(Exception):
    """Raised internally when a service-account secret can't build a session."""


def build_session(secret: bytes, scopes: Sequence[str]) -> AuthorizedSession:
    if not secret:
        msg = "Connection has no service-account credentials."
        raise CredentialsError(msg)
    try:
        info = json.loads(secret)
    except json.JSONDecodeError as exc:
        msg = f"Connection secret is not valid JSON: {exc}"
        raise CredentialsError(msg) from exc
    if not isinstance(info, dict):
        msg = "Connection secret must be a JSON object (service-account key)."
        raise CredentialsError(msg)
    # google-auth ships no type stubs, so its callables read as untyped.
    # Bind them to typed locals (binding, unlike calling, doesn't trip
    # no-untyped-call) so the call sites stay typed without inline ignores.
    # Resolved per-call so test patches on these symbols still apply.
    make_credentials: _CredentialsFactory = Credentials.from_service_account_info
    authorized_session: Callable[[Credentials], AuthorizedSession] = AuthorizedSession
    try:
        credentials = make_credentials(info, scopes=list(scopes))
    except (ValueError, GoogleAuthError) as exc:
        msg = f"Invalid service-account credentials: {exc}"
        raise CredentialsError(msg) from exc
    return mount_retries(authorized_session(credentials))


def probe(*, session: AuthorizedSession, url: str, what: str) -> CheckResult:
    try:
        response = session.get(url, timeout=10)
    except (requests.RequestException, GoogleAuthError) as exc:
        return CheckResult(
            outcome=CheckOutcome.AUTH_FAILED,
            hint=f"{what.capitalize()} request failed: {exc}",
        )
    if response.ok:
        return CheckResult(outcome=CheckOutcome.OK, hint="")
    body = (response.text or "")[:ERROR_HINT_LIMIT]
    if response.status_code == HTTP_UNAUTHORIZED:
        return CheckResult(outcome=CheckOutcome.AUTH_FAILED, hint=body)
    if response.status_code == HTTP_FORBIDDEN:
        return CheckResult(
            outcome=CheckOutcome.FORBIDDEN,
            hint=f"Service account cannot access this {what}: {body}",
        )
    if response.status_code == HTTP_NOT_FOUND:
        return CheckResult(
            outcome=CheckOutcome.NOT_FOUND,
            hint=f"{what.capitalize()} not found: {body}",
        )
    return CheckResult(
        outcome=CheckOutcome.AUTH_FAILED,
        hint=f"Unexpected {response.status_code} from Google: {body}",
    )
