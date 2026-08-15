"""Google Sheets access: spreadsheet metadata and the whole-tab writer."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import quote

import requests
from google.auth.exceptions import GoogleAuthError
from pydantic import BaseModel, Field

from ludamus.links.google_auth import ERROR_HINT_LIMIT, CredentialsError, build_session
from ludamus.pacts.sheets import SheetExportError, SheetWriterProtocol

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

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


class GoogleSheetsWriter(SheetWriterProtocol):
    """Replaces the first tab of a spreadsheet with the given rows."""

    def __init__(self, scopes: Sequence[str] = SHEETS_WRITE_SCOPES) -> None:
        self._scopes = tuple(scopes)

    def write_rows(
        self, *, secret: bytes, spreadsheet_id: str, rows: list[list[str]]
    ) -> None:
        try:
            session = build_session(secret, self._scopes)
        except CredentialsError as exc:
            raise SheetExportError(str(exc)) from exc
        # A1-quote the tab title: a bare title that parses as a cell reference
        # (a tab named "A1") or contains an apostrophe would otherwise be read
        # as a range, writing a single cell instead of the tab.
        title = _a1_quote(self._first_tab_title(session, spreadsheet_id))
        height, width = self._old_extent(
            session=session, spreadsheet_id=spreadsheet_id, title=title
        )
        # A single atomic write: padding with "" out to the previous data's
        # extent overwrites stale cells left by a longer or wider export, and
        # a failed request leaves the old data fully intact.
        self._call(
            what="Spreadsheet write",
            send=lambda: session.put(
                SHEETS_UPDATE_URL.format(
                    sheet_id=spreadsheet_id, range=quote(f"{title}!A1", safe="")
                ),
                json={"values": _pad_to_extent(rows=rows, height=height, width=width)},
                timeout=30,
            ),
        )

    def _old_extent(
        self, *, session: AuthorizedSession, spreadsheet_id: str, title: str
    ) -> tuple[int, int]:
        # A bare tab name (no A1 column bounds) returns the tab's whole data
        # region, so the extent is not capped at column Z or cut short by
        # blank cells in column A.
        response = self._call(
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

    def _first_tab_title(self, session: AuthorizedSession, spreadsheet_id: str) -> str:
        response = self._call(
            what="Spreadsheet metadata",
            send=lambda: session.get(
                SHEETS_META_URL.format(sheet_id=spreadsheet_id), timeout=10
            ),
        )
        meta = SpreadsheetMeta.model_validate(response.json())
        if not meta.sheets or not (title := meta.sheets[0].properties.title):
            msg = "Spreadsheet has no sheet tab to write into."
            raise SheetExportError(msg)
        return title

    @staticmethod
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
