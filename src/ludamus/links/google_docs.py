"""Google Docs proposal importer integration implementation."""

from __future__ import annotations

import json
from contextlib import suppress
from typing import TYPE_CHECKING
from urllib.parse import quote

import requests
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.service_account import Credentials
from pydantic import BaseModel, ConfigDict, Field

from ludamus.pacts.chronology import (
    CheckOutcome,
    CheckResult,
    IntegrationKind,
    SourceQuestion,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

GOOGLE_SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/forms.body.readonly",
)
SHEETS_API_URL = "https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/A1:Z1"
SHEETS_META_URL = (
    "https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}"
    "?fields=sheets.properties.title"
)
SHEETS_VALUES_URL = (
    "https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{range}"
)
FORMS_API_URL = "https://forms.googleapis.com/v1/forms/{form_id}"
ERROR_HINT_LIMIT = 200
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404


class _CredentialsError(Exception):
    """Raised internally when a service-account secret can't build a session."""


def _disambiguate(titles: list[str]) -> list[str]:
    # Google Forms permits two questions with the same title; the recipe
    # (dict[title, QuestionTarget]) and the response row (dict[header, str])
    # would silently collapse them into one. Suffix the 2nd, 3rd, ...
    # occurrences so each column ends up with a unique key on both sides.
    seen: dict[str, int] = {}
    result: list[str] = []
    for title in titles:
        seen[title] = (occurrence := seen.get(title, 0) + 1)
        result.append(title if occurrence == 1 else f"{title} ({occurrence})")
    return result


def _row_to_dict(headers: list[str], row: list[str]) -> dict[str, str]:
    # Sheets omits trailing empty cells, so a row may be shorter than headers.
    return {header: row[i] if i < len(row) else "" for i, header in enumerate(headers)}


class _SheetProperties(BaseModel):
    title: str = ""


class _Sheet(BaseModel):
    properties: _SheetProperties = Field(default_factory=_SheetProperties)


class _SpreadsheetMeta(BaseModel):
    sheets: list[_Sheet] = []


class _FormOption(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    value: str = ""
    is_other: bool = Field(default=False, alias="isOther")


class _ChoiceQuestion(BaseModel):
    type: str = ""
    options: list[_FormOption] = []


class _Question(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    choice_question: _ChoiceQuestion | None = Field(
        default=None, alias="choiceQuestion"
    )


class _QuestionItem(BaseModel):
    question: _Question = Field(default_factory=_Question)


class _FormItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str = ""
    question_item: _QuestionItem | None = Field(default=None, alias="questionItem")


class _FormSchema(BaseModel):
    items: list[_FormItem] = []


def _source_question(item: _FormItem) -> SourceQuestion | None:
    # Map a Forms API item to the importer's question vocabulary; non-questions
    # (page breaks, section headers) and untitled questions return None.
    if item.question_item is None or not item.title:
        return None
    if (choice := item.question_item.question.choice_question) is None:
        return SourceQuestion(title=item.title)
    return SourceQuestion(
        title=item.title,
        field_type="select",
        is_multiple=choice.type == "CHECKBOX",
        allow_custom=any(option.is_other for option in choice.options),
        options=[opt.value for opt in choice.options if not opt.is_other and opt.value],
    )


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

    def fetch_questions(
        self, secret: bytes, config: GoogleDocsProposalConfig
    ) -> list[SourceQuestion]:
        try:
            session = self._session(secret)
        except _CredentialsError:
            return []
        response: requests.Response | None = None
        with suppress(requests.RequestException, GoogleAuthError):
            response = session.get(
                FORMS_API_URL.format(form_id=config.form_id), timeout=10
            )
        if response is None or not response.ok:
            return []
        schema = _FormSchema.model_validate(response.json())
        questions = [
            question
            for item in schema.items
            if (question := _source_question(item)) is not None
        ]
        dedup_questions = {}
        for question in questions:
            if question.title not in dedup_questions:
                dedup_questions[question.title] = question
            else:
                existing_question = dedup_questions[question.title]
                if existing_question.field_type != question.field_type:
                    raise ValueError("Duplicate questions!")
                if existing_question.field_type == "select":
                    existing_question.is_multiple |= question.is_multiple
                    existing_question.allow_custom |= question.allow_custom
                    existing_question.options = list(
                        set(existing_question.options + question.options)
                    )

        return dedup_questions

    def fetch_responses(
        self, secret: bytes, config: BaseModel, header_row: int = 1
    ) -> list[dict[str, str]]:
        # `header_row` is 1-indexed to match the row numbers the operator sees
        # in the browser; the first data row is `header_row + 1`.
        if not isinstance(config, GoogleDocsProposalConfig):
            return []
        try:
            session = self._session(secret)
        except _CredentialsError:
            return []
        if not (title := self._responses_tab_title(session, config.sheet_id)):
            return []
        response: requests.Response | None = None
        with suppress(requests.RequestException, GoogleAuthError):
            # A bare tab name (no A1 column bounds) returns the tab's whole data
            # region — every column and row — so a wide form is not capped at Z.
            response = session.get(
                SHEETS_VALUES_URL.format(sheet_id=config.sheet_id, range=quote(title)),
                timeout=30,
            )
        if response is None or not response.ok:
            return []
        if not (values := response.json().get("values") or []):
            return []
        if not 1 <= header_row <= len(values):
            return []
        headers = _disambiguate([str(cell) for cell in values[header_row - 1]])
        return [_row_to_dict(headers, row) for row in values[header_row:]]

    @staticmethod
    def _responses_tab_title(session: AuthorizedSession, sheet_id: str) -> str:
        # Responses live on the spreadsheet's first tab (a form-linked sheet has
        # only that one); read its title so the values request can name it.
        response: requests.Response | None = None
        with suppress(requests.RequestException, GoogleAuthError):
            response = session.get(
                SHEETS_META_URL.format(sheet_id=sheet_id), timeout=10
            )
        if response is None or not response.ok:
            return ""
        meta = _SpreadsheetMeta.model_validate(response.json())
        return meta.sheets[0].properties.title if meta.sheets else ""

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
