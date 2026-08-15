"""Integration tests for the Google Sheets whole-tab writer.

`google.auth` is mocked at the package boundary (credentials + authorized
session); the writer's own padding, quoting and error mapping run for real.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests

from ludamus.links.google_sheets import (
    SHEETS_META_URL,
    SHEETS_UPDATE_URL,
    GoogleSheetsWriter,
)
from ludamus.pacts.sheets import SheetExportError

SECRET = b'{"type": "service_account"}'
EXPORT_ROWS = [["Creator", "Accreditation type"], ["Alice", "Guest"]]


def _resp(*, ok: bool, status_code: int = 200, text: str = "") -> MagicMock:
    response = MagicMock()
    response.ok = ok
    response.status_code = status_code
    response.text = text
    return response


def _meta_with_title(title: str = "Form Responses 1") -> MagicMock:
    return MagicMock(
        ok=True, json=lambda: {"sheets": [{"properties": {"title": title}}]}
    )


def _route_get(*, values: list[list[str]], title: str = "Form Responses 1"):
    # The writer first reads spreadsheet metadata (for the tab title), then the
    # tab's values; route each call by URL so call order/count is irrelevant.
    meta = _meta_with_title(title)
    vals = MagicMock(ok=True, json=lambda: {"values": values})

    def get(url: str, **_kwargs: object) -> MagicMock:
        return vals if "/values/" in url else meta

    return get


@pytest.fixture(name="google")
def google_fixture():
    with (
        patch(
            "ludamus.links.google_auth.Credentials.from_service_account_info"
        ) as creds,
        patch("ludamus.links.google_auth.AuthorizedSession") as session_cls,
    ):
        yield SimpleNamespace(creds=creds, session=session_cls.return_value)


class TestGoogleSheetsWriter:
    def test_writes_the_first_tab_in_a_single_request(self, google):
        google.session.get.side_effect = _route_get(
            values=[["x", "y"]] * len(EXPORT_ROWS)
        )
        google.session.put.return_value = _resp(ok=True)

        GoogleSheetsWriter().write_rows(
            secret=SECRET, spreadsheet_id="sheet-1", rows=EXPORT_ROWS
        )

        google.creds.assert_called_once_with(
            {"type": "service_account"},
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        google.session.get.assert_any_call(
            SHEETS_META_URL.format(sheet_id="sheet-1"), timeout=10
        )
        google.session.post.assert_not_called()
        google.session.put.assert_called_once_with(
            SHEETS_UPDATE_URL.format(
                sheet_id="sheet-1", range="%27Form%20Responses%201%27%21A1"
            ),
            json={"values": EXPORT_ROWS},
            timeout=30,
        )

    def test_pads_a_smaller_export_to_overwrite_the_old_extent(self, google):
        # Previous export: 4 rows x 3 columns. The new 2x2 payload is padded
        # with "" so the single write also blanks the stale row and column.
        google.session.get.side_effect = _route_get(values=[["x", "y", "z"]] * 4)
        google.session.put.return_value = _resp(ok=True)

        GoogleSheetsWriter().write_rows(
            secret=SECRET, spreadsheet_id="sheet-1", rows=EXPORT_ROWS
        )

        google.session.post.assert_not_called()
        google.session.put.assert_called_once_with(
            SHEETS_UPDATE_URL.format(
                sheet_id="sheet-1", range="%27Form%20Responses%201%27%21A1"
            ),
            json={
                "values": [
                    ["Creator", "Accreditation type", ""],
                    ["Alice", "Guest", ""],
                    ["", "", ""],
                    ["", "", ""],
                ]
            },
            timeout=30,
        )

    def test_quotes_tab_title_that_looks_like_a_cell_reference(self, google):
        google.session.get.side_effect = _route_get(values=[], title="A1")
        google.session.put.return_value = _resp(ok=True)

        GoogleSheetsWriter().write_rows(
            secret=SECRET, spreadsheet_id="sheet-1", rows=EXPORT_ROWS
        )

        google.session.put.assert_called_once_with(
            SHEETS_UPDATE_URL.format(sheet_id="sheet-1", range="%27A1%27%21A1"),
            json={"values": EXPORT_ROWS},
            timeout=30,
        )

    def test_quotes_apostrophe_in_tab_title(self, google):
        google.session.get.side_effect = _route_get(values=[], title="It's")
        google.session.put.return_value = _resp(ok=True)

        GoogleSheetsWriter().write_rows(
            secret=SECRET, spreadsheet_id="sheet-1", rows=EXPORT_ROWS
        )

        google.session.put.assert_called_once_with(
            SHEETS_UPDATE_URL.format(sheet_id="sheet-1", range="%27It%27%27s%27%21A1"),
            json={"values": EXPORT_ROWS},
            timeout=30,
        )

    def test_missing_secret_raises_without_any_request(self, google):
        with pytest.raises(
            SheetExportError, match="Connection has no service-account credentials"
        ):
            GoogleSheetsWriter().write_rows(
                secret=b"", spreadsheet_id="sheet-1", rows=EXPORT_ROWS
            )

        google.session.get.assert_not_called()

    def test_invalid_credentials_raise(self, google):
        google.creds.side_effect = ValueError("bad key")

        with pytest.raises(
            SheetExportError, match="Invalid service-account credentials: bad key"
        ):
            GoogleSheetsWriter().write_rows(
                secret=SECRET, spreadsheet_id="sheet-1", rows=EXPORT_ROWS
            )

    def test_metadata_failure_raises_before_writing(self, google):
        google.session.get.return_value = _resp(ok=False, status_code=403, text="deny")

        with pytest.raises(
            SheetExportError, match="Spreadsheet metadata request failed with 403: deny"
        ):
            GoogleSheetsWriter().write_rows(
                secret=SECRET, spreadsheet_id="sheet-1", rows=EXPORT_ROWS
            )

        google.session.post.assert_not_called()
        google.session.put.assert_not_called()

    def test_spreadsheet_without_tabs_raises(self, google):
        google.session.get.return_value = MagicMock(
            ok=True, json=lambda: {"sheets": []}
        )

        with pytest.raises(
            SheetExportError, match="Spreadsheet has no sheet tab to write into"
        ):
            GoogleSheetsWriter().write_rows(
                secret=SECRET, spreadsheet_id="sheet-1", rows=EXPORT_ROWS
            )

    def test_untitled_tab_raises(self, google):
        google.session.get.return_value = _meta_with_title("")

        with pytest.raises(
            SheetExportError, match="Spreadsheet has no sheet tab to write into"
        ):
            GoogleSheetsWriter().write_rows(
                secret=SECRET, spreadsheet_id="sheet-1", rows=EXPORT_ROWS
            )

    def test_extent_read_failure_raises_before_writing(self, google):
        def get(url: str, **_kwargs: object) -> MagicMock:
            if "/values/" in url:
                return _resp(ok=False, status_code=403, text="deny")
            return _meta_with_title()

        google.session.get.side_effect = get

        with pytest.raises(
            SheetExportError, match="Spreadsheet read request failed with 403: deny"
        ):
            GoogleSheetsWriter().write_rows(
                secret=SECRET, spreadsheet_id="sheet-1", rows=EXPORT_ROWS
            )

        google.session.put.assert_not_called()

    def test_write_failure_raises(self, google):
        google.session.get.side_effect = _route_get(values=[["x"]] * 5)
        google.session.put.return_value = _resp(ok=False, status_code=500, text="boom")

        with pytest.raises(
            SheetExportError, match="Spreadsheet write request failed with 500: boom"
        ):
            GoogleSheetsWriter().write_rows(
                secret=SECRET, spreadsheet_id="sheet-1", rows=EXPORT_ROWS
            )

    def test_request_exception_raises(self, google):
        google.session.get.side_effect = _route_get(values=[])
        google.session.put.side_effect = requests.RequestException("timeout")

        with pytest.raises(
            SheetExportError, match="Spreadsheet write request failed: timeout"
        ):
            GoogleSheetsWriter().write_rows(
                secret=SECRET, spreadsheet_id="sheet-1", rows=EXPORT_ROWS
            )
