"""Google Sheets access: spreadsheet metadata and the whole-tab writer."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import quote

import requests
from google.auth.exceptions import GoogleAuthError
from pydantic import BaseModel, Field

from ludamus.links.google_auth import (
    ERROR_HINT_LIMIT,
    CredentialsError,
    build_session,
    probe,
)
from ludamus.pacts.chronology import (
    CheckOutcome,
    CheckResult,
    IntegrationImplementation,
    IntegrationKind,
)
from ludamus.pacts.konwencik import KonwencikSheetConfig
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
SHEETS_BATCH_UPDATE_URL = (
    "https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}:batchUpdate"
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
        self,
        *,
        secret: bytes,
        spreadsheet_id: str,
        rows: list[list[str]],
        tab: str = "",
    ) -> None:
        try:
            session = build_session(secret, self._scopes)
        except CredentialsError as exc:
            raise SheetExportError(str(exc)) from exc
        # A1-quote the tab title: a bare title that parses as a cell reference
        # (a tab named "A1") or contains an apostrophe would otherwise be read
        # as a range, writing a single cell instead of the tab.
        title = _a1_quote(self._resolve_tab(session, spreadsheet_id, tab))
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

    def _resolve_tab(
        self, session: AuthorizedSession, spreadsheet_id: str, tab: str
    ) -> str:
        response = self._call(
            what="Spreadsheet metadata",
            send=lambda: session.get(
                SHEETS_META_URL.format(sheet_id=spreadsheet_id), timeout=10
            ),
        )
        meta = SpreadsheetMeta.model_validate(response.json())
        titles = [sheet.properties.title for sheet in meta.sheets]
        if tab:
            if tab not in titles:
                msg = f'Spreadsheet has no tab named "{tab}".'
                raise SheetExportError(msg)
            return tab
        if not titles or not titles[0]:
            msg = "Spreadsheet has no sheet tab to write into."
            raise SheetExportError(msg)
        return titles[0]

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


class KonwencikSheetExporter(IntegrationImplementation):
    """Pushes an event's agenda into the tab Konwencik reads."""

    kind: IntegrationKind = IntegrationKind.EXPORT
    config_model: type[BaseModel] = KonwencikSheetConfig

    def __init__(self, scopes: Sequence[str] = SHEETS_WRITE_SCOPES) -> None:
        self._scopes = tuple(scopes)

    def check(self, secret: bytes, config: BaseModel) -> CheckResult:
        if not isinstance(config, KonwencikSheetConfig):
            return CheckResult(
                outcome=CheckOutcome.AUTH_FAILED,
                hint="Configuration is not a Konwencik sheet config.",
            )
        try:
            session = build_session(secret, self._scopes)
        except CredentialsError as exc:
            return CheckResult(outcome=CheckOutcome.AUTH_FAILED, hint=str(exc))

        # An empty batchUpdate changes nothing but is refused for a viewer, so
        # unlike a metadata GET it proves the write access the export needs.
        write = probe(
            send=lambda: session.post(
                SHEETS_BATCH_UPDATE_URL.format(sheet_id=config.spreadsheet_id),
                json={"requests": []},
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
        meta_url = SHEETS_META_URL.format(sheet_id=config.spreadsheet_id)
        try:
            response = session.get(meta_url, timeout=10)
        except (requests.RequestException, GoogleAuthError) as exc:
            return CheckResult(
                outcome=CheckOutcome.AUTH_FAILED,
                hint=f"Spreadsheet metadata request failed: {exc}",
            )
        if not response.ok:
            return CheckResult(
                outcome=CheckOutcome.AUTH_FAILED,
                hint=(
                    f"Unexpected {response.status_code} from Google: "
                    f"{(response.text or '')[:ERROR_HINT_LIMIT]}"
                ),
            )
        titles = [
            sheet.properties.title
            for sheet in SpreadsheetMeta.model_validate(response.json()).sheets
        ]
        if config.tab not in titles:
            return CheckResult(
                outcome=CheckOutcome.NOT_FOUND,
                hint=(
                    f'Spreadsheet has no tab named "{config.tab}". '
                    f"Tabs found: {', '.join(titles) or 'none'}."
                ),
            )
        return CheckResult(
            outcome=CheckOutcome.OK, hint=f'Write possible, tab "{config.tab}".'
        )
