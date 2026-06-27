"""Google Docs proposal importer integration implementation."""

from __future__ import annotations

import json
from contextlib import suppress
from typing import TYPE_CHECKING, Protocol
from urllib.parse import quote

import requests
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.service_account import Credentials
from pydantic import BaseModel, ConfigDict, Field

from ludamus.pacts.chronology import (
    CheckOutcome,
    CheckResult,
    IntegrationImplementation,
    IntegrationKind,
    SourceQuestion,
)
from ludamus.pacts.submissions import ImportRow

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence


class _CredentialsFactory(Protocol):
    def __call__(
        self, info: Mapping[str, object], *, scopes: list[str]
    ) -> Credentials: ...


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
    # Two sheet columns with the same header would collapse to a single dict
    # key, losing one column's value. Suffix the 2nd, 3rd, ... occurrences so
    # each column survives. `ImportRow.get_value` re-collapses these at the
    # mill's value-access call site (the form question they belong to is the
    # same), surfacing conflicting non-empty values as `DuplicateValueError`
    # for the mill to convert into a per-row skip.
    seen: dict[str, int] = {}
    result: list[str] = []
    for title in titles:
        seen[title] = (occurrence := seen.get(title, 0) + 1)
        result.append(title if occurrence == 1 else f"{title} ({occurrence})")
    return result


def _row_to_import_row(headers: list[str], row: list[str]) -> ImportRow:
    # Sheets omits trailing empty cells, so a row may be shorter than headers.
    return ImportRow(
        {header: row[i] if i < len(row) else "" for i, header in enumerate(headers)}
    )


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


class _FormSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    email_collection_type: str = Field(default="", alias="emailCollectionType")


class _FormSchema(BaseModel):
    items: list[_FormItem] = []
    settings: _FormSettings = Field(default_factory=_FormSettings)


# Forms with email collection enabled get an auto-added email column in the
# linked sheet that doesn't appear in the Forms API items[]. The operator names
# the column position (1-indexed) via ImportSettings.email_column; the importer
# reads the sheet header at that position and synthesizes a SourceQuestion the
# recipe can map to session.contact_email.
_EMAIL_COLLECTION_VALUES = frozenset({"RESPONDER_INPUT", "VERIFIED"})


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


class GoogleDocsProposalImporter(IntegrationImplementation):
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
            session=session,
            url=SHEETS_API_URL.format(sheet_id=config.sheet_id),
            what="spreadsheet",
        )
        if sheet_outcome.outcome != CheckOutcome.OK:
            return sheet_outcome
        return self._probe(
            session=session,
            url=FORMS_API_URL.format(form_id=config.form_id),
            what="form",
        )

    def fetch_questions(
        self,
        *,
        secret: bytes,
        config: BaseModel,
        header_row: int = 1,
        email_column: int | None = None,
    ) -> list[SourceQuestion]:
        if not isinstance(config, GoogleDocsProposalConfig):
            return []
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
        dedup_questions: dict[str, SourceQuestion] = {}
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
                        dict.fromkeys([*existing_question.options, *question.options])
                    )
        if (
            schema.settings.email_collection_type in _EMAIL_COLLECTION_VALUES
            and email_column is not None
            and (
                email_title := self._fetch_sheet_header(
                    session=session,
                    sheet_id=config.sheet_id,
                    header_row=header_row,
                    column=email_column,
                )
            )
            and email_title not in dedup_questions
        ):
            dedup_questions[email_title] = SourceQuestion(title=email_title)

        return list(dedup_questions.values())

    def _fetch_sheet_header(
        self, *, session: AuthorizedSession, sheet_id: str, header_row: int, column: int
    ) -> str:
        # Read the cell at (header_row, column), both 1-indexed, from the
        # responses tab so the email column's actual label drives the recipe.
        # Fetches the whole header row via A1 range notation and picks the
        # column out by index — Sheets API is picky about R1C1 mixed with a
        # sheet prefix, but a plain row range is universally supported.
        if column < 1 or header_row < 1:
            return ""
        if not (title := self._responses_tab_title(session, sheet_id)):
            return ""
        row_range = f"{title}!{header_row}:{header_row}"
        response: requests.Response | None = None
        with suppress(requests.RequestException, GoogleAuthError):
            response = session.get(
                SHEETS_VALUES_URL.format(
                    sheet_id=sheet_id, range=quote(row_range, safe="")
                ),
                timeout=10,
            )
        if response is None or not response.ok:
            return ""
        if not (values := response.json().get("values") or []):
            return ""
        row = values[0]
        if column > len(row):
            return ""
        return str(row[column - 1])

    def fetch_responses(
        self, *, secret: bytes, config: BaseModel, header_row: int = 1
    ) -> list[ImportRow]:
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
                SHEETS_VALUES_URL.format(
                    sheet_id=config.sheet_id, range=quote(title, safe="")
                ),
                timeout=30,
            )
        if response is None or not response.ok:
            return []
        if not (values := response.json().get("values") or []):
            return []
        if not 1 <= header_row <= len(values):
            return []
        headers = _disambiguate([str(cell) for cell in values[header_row - 1]])
        return [_row_to_import_row(headers, row) for row in values[header_row:]]

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
        # google-auth ships no type stubs, so its callables read as untyped.
        # Bind them to typed locals (binding, unlike calling, doesn't trip
        # no-untyped-call) so the call sites stay typed without inline ignores.
        # Resolved per-call so test patches on these symbols still apply.
        make_credentials: _CredentialsFactory = Credentials.from_service_account_info
        authorized_session: Callable[[Credentials], AuthorizedSession] = (
            AuthorizedSession
        )
        try:
            credentials = make_credentials(info, scopes=list(self._scopes))
        except (ValueError, GoogleAuthError) as exc:
            msg = f"Invalid service-account credentials: {exc}"
            raise _CredentialsError(msg) from exc
        return authorized_session(credentials)

    @staticmethod
    def _probe(*, session: AuthorizedSession, url: str, what: str) -> CheckResult:
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
