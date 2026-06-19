"""Google Docs proposal importer integration implementation."""

from __future__ import annotations

import json
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
FORMS_API_URL = "https://forms.googleapis.com/v1/forms/{form_id}"
ERROR_HINT_LIMIT = 200
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404


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
        if not secret:
            return CheckResult(
                outcome=CheckOutcome.AUTH_FAILED,
                hint="Connection has no service-account credentials.",
            )
        try:
            info = json.loads(secret)
        except json.JSONDecodeError as exc:
            return CheckResult(
                outcome=CheckOutcome.AUTH_FAILED,
                hint=f"Connection secret is not valid JSON: {exc}",
            )
        if not isinstance(info, dict):
            return CheckResult(
                outcome=CheckOutcome.AUTH_FAILED,
                hint="Connection secret must be a JSON object (service-account key).",
            )

        try:
            credentials: Credentials = (
                Credentials.from_service_account_info(  # type: ignore[no-untyped-call]
                    info, scopes=list(self._scopes)
                )
            )
        except (ValueError, GoogleAuthError) as exc:
            return CheckResult(
                outcome=CheckOutcome.AUTH_FAILED,
                hint=f"Invalid service-account credentials: {exc}",
            )

        session: AuthorizedSession = AuthorizedSession(
            credentials
        )  # type: ignore[no-untyped-call]
        sheet_outcome = self._probe(
            session, SHEETS_API_URL.format(sheet_id=config.sheet_id), "spreadsheet"
        )
        if sheet_outcome.outcome != CheckOutcome.OK:
            return sheet_outcome
        return self._probe(
            session, FORMS_API_URL.format(form_id=config.form_id), "form"
        )

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
