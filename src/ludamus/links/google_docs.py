"""Google Docs proposal importer integration implementation."""

from __future__ import annotations

import json
from contextlib import suppress
from typing import TYPE_CHECKING

import requests
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.service_account import Credentials
from pydantic import BaseModel

from ludamus.pacts.chronology import CheckOutcome, CheckResult, IntegrationKind

if TYPE_CHECKING:
    from collections.abc import Sequence

GOOGLE_SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/forms.body.readonly",
)
SHEETS_API_URL = "https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/A1:Z1"
SHEETS_RESPONSES_URL = (
    "https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/A:Z"
)
FORMS_API_URL = "https://forms.googleapis.com/v1/forms/{form_id}"
ERROR_HINT_LIMIT = 200
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404


class _CredentialsError(Exception):
    """Raised internally when a service-account secret can't build a session."""


def _row_to_dict(headers: list[str], row: list[object]) -> dict[str, str]:
    # Sheets omits trailing empty cells, so a row may be shorter than headers.
    return {
        header: str(row[i]) if i < len(row) else "" for i, header in enumerate(headers)
    }


class GoogleDocsProposalConfig(BaseModel):
    sheet_id: str
    form_id: str


class GoogleDocsProposalImporter:
    """Pulls proposals from a Google Sheets responses tab linked to a Form."""

    kind: IntegrationKind = IntegrationKind.IMPORT
    config_model: type[BaseModel] = GoogleDocsProposalConfig

    def __init__(self, scopes: Sequence[str] = GOOGLE_SCOPES) -> None:
        self._scopes = tuple(scopes)

    def check(self, secret: bytes, config: BaseModel) -> CheckResult:
        if not isinstance(config, GoogleDocsProposalConfig):
            return CheckResult(
                outcome=CheckOutcome.AUTH_FAILED,
                hint="Configuration is not a Google Docs proposal config.",
            )
        try:
            session = self._session(secret)
        except _CredentialsError as exc:
            return CheckResult(outcome=CheckOutcome.AUTH_FAILED, hint=str(exc))

        sheet_outcome = self._probe(
            session, SHEETS_API_URL.format(sheet_id=config.sheet_id), "spreadsheet"
        )
        if sheet_outcome.outcome != CheckOutcome.OK:
            return sheet_outcome
        return self._probe(
            session, FORMS_API_URL.format(form_id=config.form_id), "form"
        )

    def fetch_questions(self, secret: bytes, config: BaseModel) -> list[str]:
        if not isinstance(config, GoogleDocsProposalConfig):
            return []
        try:
            session = self._session(secret)
        except _CredentialsError:
            return []
        response: requests.Response | None = None
        with suppress(requests.RequestException, GoogleAuthError):
            response = session.get(
                SHEETS_API_URL.format(sheet_id=config.sheet_id), timeout=10
            )
        if response is None or not response.ok:
            return []
        values = response.json().get("values") or []
        header_row = values[0] if values else []
        return [str(cell) for cell in header_row]

    def fetch_responses(self, secret: bytes, config: BaseModel) -> list[dict[str, str]]:
        if not isinstance(config, GoogleDocsProposalConfig):
            return []
        try:
            session = self._session(secret)
        except _CredentialsError:
            return []
        response: requests.Response | None = None
        with suppress(requests.RequestException, GoogleAuthError):
            response = session.get(
                SHEETS_RESPONSES_URL.format(sheet_id=config.sheet_id), timeout=30
            )
        if response is None or not response.ok:
            return []
        if not (values := response.json().get("values") or []):
            return []
        headers = [str(cell) for cell in values[0]]
        return [_row_to_dict(headers, row) for row in values[1:]]

    def _session(self, secret: bytes) -> AuthorizedSession:
        if not secret:
            msg = "Connection has no service-account credentials."
            raise _CredentialsError(msg)
        try:
            info = json.loads(secret)
        except json.JSONDecodeError as exc:
            msg = f"Connection secret is not valid JSON: {exc}"
            raise _CredentialsError(msg) from exc
        if not isinstance(info, dict):
            msg = "Connection secret must be a JSON object (service-account key)."
            raise _CredentialsError(msg)
        try:
            credentials: Credentials = (
                Credentials.from_service_account_info(  # type: ignore[no-untyped-call]
                    info, scopes=list(self._scopes)
                )
            )
        except (ValueError, GoogleAuthError) as exc:
            msg = f"Invalid service-account credentials: {exc}"
            raise _CredentialsError(msg) from exc
        return AuthorizedSession(credentials)  # type: ignore[no-untyped-call]

    @staticmethod
    def _probe(session: AuthorizedSession, url: str, what: str) -> CheckResult:
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
