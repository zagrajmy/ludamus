"""Google Sheets access: spreadsheet metadata and the whole-tab writer."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import quote

import requests
from google.auth.exceptions import GoogleAuthError
from pydantic import BaseModel, Field

from ludamus.links.google_auth import CredentialsError, build_session, probe
from ludamus.links.http_check import ERROR_HINT_LIMIT
from ludamus.pacts.chronology import (
    CheckOutcome,
    CheckResult,
    IntegrationImplementation,
    IntegrationKind,
)
from ludamus.pacts.konwencik import KonwencikSheetConfig
from ludamus.pacts.sheets import SheetExportError, SheetWriterProtocol

if TYPE_CHECKING:
    from collections.abc import Callable

    from google.auth.transport.requests import AuthorizedSession

# Service-account credentials mint a token per requested scope set, so the
# write scope needs no re-authorization — only editor access on the target
# spreadsheet for the service account.
SHEETS_WRITE_SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)
SHEETS_API_URL = "https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/A1:Z1"
SHEETS_META_URL = (
    "https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}"
    "?fields=sheets.properties.title"
)
SHEETS_VALUES_URL = (
    "https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{range}"
)
SHEETS_UPDATE_URL = (
    "https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{range}"
    "?valueInputOption=RAW"
)
SHEETS_BATCH_UPDATE_URL = (
    "https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}:batchUpdate"
)
# Deletes developer metadata under a key nothing ever writes: it matches
# nothing and changes nothing, but still needs write access to be accepted.
NOOP_WRITE_REQUEST = {
    "deleteDeveloperMetadata": {
        "dataFilter": {"developerMetadataLookup": {"metadataKey": "ludamus-check"}}
    }
}


class _SheetProperties(BaseModel):
    title: str = ""


class _Sheet(BaseModel):
    properties: _SheetProperties = Field(default_factory=_SheetProperties)


class SpreadsheetMeta(BaseModel):
    sheets: list[_Sheet] = []


def _a1_quote(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


def _pad_to_extent(
    *, rows: list[list[str]], height: int, width: int
) -> list[list[str]]:
    width = max([width, *(len(row) for row in rows)])
    padded = [[*row, *[""] * (width - len(row))] for row in rows]
    return padded + [[""] * width] * (height - len(padded))


class _TabNotFoundError(SheetExportError):
    # The spreadsheet answered, and it has no tab to write into. A writer
    # treats it like any other export failure; a check reports NOT_FOUND
    # rather than blaming the credentials.
    pass


def _call(*, what: str, send: Callable[[], requests.Response]) -> requests.Response:
    try:
        response = send()
    except (requests.RequestException, GoogleAuthError) as exc:
        msg = f"{what} request failed: {exc}"
        raise SheetExportError(msg) from exc
    if not response.ok:
        body = (response.text or "")[:ERROR_HINT_LIMIT]
        msg = f"{what} request failed with {response.status_code}: {body}"
        raise SheetExportError(msg)
    return response


def _tab_titles(session: AuthorizedSession, spreadsheet_id: str) -> list[str]:
    response = _call(
        what="Spreadsheet metadata",
        send=lambda: session.get(
            SHEETS_META_URL.format(sheet_id=spreadsheet_id), timeout=10
        ),
    )
    meta = SpreadsheetMeta.model_validate(response.json())
    return [sheet.properties.title for sheet in meta.sheets]


def _resolve_tab(titles: list[str], tab: str) -> str:
    # A blank tab means the first one. That is the writer's contract, which
    # the discounts export relies on, so the check has to resolve it the same
    # way or it reports a red cross on a configuration that exports fine.
    if tab:
        if tab not in titles:
            msg = f'Spreadsheet has no tab named "{tab}".'
            raise _TabNotFoundError(msg)
        return tab
    if not titles or not titles[0]:
        msg = "Spreadsheet has no sheet tab to write into."
        raise _TabNotFoundError(msg)
    return titles[0]


class GoogleSheetsWriter(SheetWriterProtocol):
    """Replaces the first tab of a spreadsheet with the given rows."""

    def write_rows(
        self,
        *,
        secret: bytes,
        spreadsheet_id: str,
        rows: list[list[str]],
        tab: str = "",
    ) -> None:
        try:
            session = build_session(secret, SHEETS_WRITE_SCOPES)
        except CredentialsError as exc:
            raise SheetExportError(str(exc)) from exc
        # A1-quote the tab title: a bare title that parses as a cell reference
        # (a tab named "A1") or contains an apostrophe would otherwise be read
        # as a range, writing a single cell instead of the tab.
        title = _a1_quote(_resolve_tab(_tab_titles(session, spreadsheet_id), tab))
        height, width = self._old_extent(
            session=session, spreadsheet_id=spreadsheet_id, title=title
        )
        # A single atomic write: padding with "" out to the previous data's
        # extent overwrites stale cells left by a longer or wider export, and
        # a failed request leaves the old data fully intact.
        _call(
            what="Spreadsheet write",
            send=lambda: session.put(
                SHEETS_UPDATE_URL.format(
                    sheet_id=spreadsheet_id, range=quote(f"{title}!A1", safe="")
                ),
                json={"values": _pad_to_extent(rows=rows, height=height, width=width)},
                timeout=30,
            ),
        )

    @staticmethod
    def _old_extent(
        *, session: AuthorizedSession, spreadsheet_id: str, title: str
    ) -> tuple[int, int]:
        # A bare tab name (no A1 column bounds) returns the tab's whole data
        # region, so the extent is not capped at column Z or cut short by
        # blank cells in column A.
        response = _call(
            what="Spreadsheet read",
            send=lambda: session.get(
                SHEETS_VALUES_URL.format(
                    sheet_id=spreadsheet_id, range=quote(title, safe="")
                ),
                timeout=10,
            ),
        )
        values = response.json().get("values") or []
        return len(values), max((len(row) for row in values), default=0)


class KonwencikSheetExporter(IntegrationImplementation):
    """Pushes an event's agenda into the tab Konwencik reads."""

    kind: IntegrationKind = IntegrationKind.EXPORT
    config_model: type[BaseModel] = KonwencikSheetConfig

    def check(self, secret: bytes, config: BaseModel) -> CheckResult:
        if not isinstance(config, KonwencikSheetConfig):
            return CheckResult(
                outcome=CheckOutcome.AUTH_FAILED,
                hint="Configuration is not a Konwencik sheet config.",
            )
        try:
            session = build_session(secret, SHEETS_WRITE_SCOPES)
        except CredentialsError as exc:
            return CheckResult(outcome=CheckOutcome.AUTH_FAILED, hint=str(exc))

        # A no-op batchUpdate is refused for a viewer, so unlike a metadata GET
        # it proves the write access the export needs. An empty request list
        # would be simpler, but Google rejects it with a 400 ("Must specify at
        # least one request") before it ever looks at permissions.
        write = probe(
            send=lambda: session.post(
                SHEETS_BATCH_UPDATE_URL.format(sheet_id=config.spreadsheet_id),
                json={"requests": [NOOP_WRITE_REQUEST]},
                timeout=10,
            ),
            what="spreadsheet",
        )
        if write.outcome == CheckOutcome.FORBIDDEN:
            return CheckResult(
                outcome=write.outcome,
                hint=(
                    "Share the spreadsheet as an editor with the service-account "
                    f"address: {write.hint}"
                ),
            )
        if write.outcome != CheckOutcome.OK:
            return write
        return self._check_tab(session=session, config=config)

    @staticmethod
    def _check_tab(
        *, session: AuthorizedSession, config: KonwencikSheetConfig
    ) -> CheckResult:
        try:
            titles = _tab_titles(session, config.spreadsheet_id)
        except SheetExportError as exc:
            return CheckResult(outcome=CheckOutcome.AUTH_FAILED, hint=str(exc))
        try:
            _resolve_tab(titles, config.tab)
        except _TabNotFoundError as exc:
            return CheckResult(
                outcome=CheckOutcome.NOT_FOUND,
                hint=f"{exc} Tabs found: {', '.join(titles) or 'none'}.",
            )
        # No hint on the happy path: the template says "Check passed." in the
        # organiser's language, and a sentence composed here cannot be
        # translated.
        return CheckResult(outcome=CheckOutcome.OK)
