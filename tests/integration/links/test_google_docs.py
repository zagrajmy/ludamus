"""Integration tests for the Google Docs proposal importer.

`google.auth` is mocked at the package boundary (credentials + authorized
session); the importer's own `check` / `_probe` logic runs for real, so the
outcome mapping is exercised end to end.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests
from pydantic import BaseModel

from ludamus.links.google_docs import (
    FORMS_API_URL,
    SHEETS_API_URL,
    GoogleDocsProposalConfig,
    GoogleDocsProposalImporter,
)
from ludamus.pacts.chronology import CheckOutcome

SECRET = b'{"type": "service_account"}'
CONFIG = GoogleDocsProposalConfig(sheet_id="sheet-1", form_id="form-1")


class _OtherConfig(BaseModel):
    """A config that is not a `GoogleDocsProposalConfig`."""


def _resp(*, ok: bool, status_code: int = 200, text: str = "") -> MagicMock:
    response = MagicMock()
    response.ok = ok
    response.status_code = status_code
    response.text = text
    return response


@pytest.fixture(name="google")
def google_fixture():
    with (
        patch(
            "ludamus.links.google_docs.Credentials.from_service_account_info"
        ) as creds,
        patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
    ):
        yield SimpleNamespace(creds=creds, session=session_cls.return_value)


class TestGoogleDocsProposalImporterCheckGuards:
    def test_wrong_config_type(self):
        result = GoogleDocsProposalImporter().check(SECRET, _OtherConfig())

        assert result.outcome == CheckOutcome.AUTH_FAILED
        assert result.hint == "Configuration is not a Google Docs proposal config."

    def test_missing_secret(self):
        result = GoogleDocsProposalImporter().check(b"", CONFIG)

        assert result.outcome == CheckOutcome.AUTH_FAILED
        assert result.hint == "Connection has no service-account credentials."

    def test_secret_not_json(self):
        result = GoogleDocsProposalImporter().check(b"not-json", CONFIG)

        assert result.outcome == CheckOutcome.AUTH_FAILED
        assert "not valid JSON" in result.hint

    def test_secret_json_but_not_object(self):
        result = GoogleDocsProposalImporter().check(b"123", CONFIG)

        assert result.outcome == CheckOutcome.AUTH_FAILED
        assert result.hint == (
            "Connection secret must be a JSON object (service-account key)."
        )

    def test_invalid_credentials(self, google):
        google.creds.side_effect = ValueError("bad key")

        result = GoogleDocsProposalImporter().check(SECRET, CONFIG)

        assert result.outcome == CheckOutcome.AUTH_FAILED
        assert result.hint == "Invalid service-account credentials: bad key"
        google.creds.assert_called_once()
        google.session.get.assert_not_called()


class TestGoogleDocsProposalImporterProbe:
    def test_ok_probes_sheet_then_form(self, google):
        google.session.get.return_value = _resp(ok=True)

        result = GoogleDocsProposalImporter().check(SECRET, CONFIG)

        assert result.outcome == CheckOutcome.OK
        assert not result.hint
        assert google.session.get.call_count == 1 + 1  # spreadsheet + form
        google.session.get.assert_any_call(
            SHEETS_API_URL.format(sheet_id="sheet-1"), timeout=10
        )
        google.session.get.assert_any_call(
            FORMS_API_URL.format(form_id="form-1"), timeout=10
        )

    def test_form_probe_failure_after_sheet_ok(self, google):
        google.session.get.side_effect = [
            _resp(ok=True),
            _resp(ok=False, status_code=404, text="gone"),
        ]

        result = GoogleDocsProposalImporter().check(SECRET, CONFIG)

        assert result.outcome == CheckOutcome.NOT_FOUND
        assert "Form not found" in result.hint

    def test_unauthorized(self, google):
        google.session.get.return_value = _resp(ok=False, status_code=401, text="nope")

        result = GoogleDocsProposalImporter().check(SECRET, CONFIG)

        assert result.outcome == CheckOutcome.AUTH_FAILED
        assert result.hint == "nope"
        google.session.get.assert_called_once_with(
            SHEETS_API_URL.format(sheet_id="sheet-1"), timeout=10
        )

    def test_forbidden(self, google):
        google.session.get.return_value = _resp(ok=False, status_code=403, text="deny")

        result = GoogleDocsProposalImporter().check(SECRET, CONFIG)

        assert result.outcome == CheckOutcome.FORBIDDEN
        assert "Service account cannot access this spreadsheet" in result.hint

    def test_not_found(self, google):
        google.session.get.return_value = _resp(ok=False, status_code=404, text="404")

        result = GoogleDocsProposalImporter().check(SECRET, CONFIG)

        assert result.outcome == CheckOutcome.NOT_FOUND
        assert "Spreadsheet not found" in result.hint

    def test_unexpected_status(self, google):
        google.session.get.return_value = _resp(ok=False, status_code=500, text="boom")

        result = GoogleDocsProposalImporter().check(SECRET, CONFIG)

        assert result.outcome == CheckOutcome.AUTH_FAILED
        assert "Unexpected 500 from Google" in result.hint

    def test_request_exception(self, google):
        google.session.get.side_effect = requests.RequestException("timeout")

        result = GoogleDocsProposalImporter().check(SECRET, CONFIG)

        assert result.outcome == CheckOutcome.AUTH_FAILED
        assert "Spreadsheet request failed: timeout" in result.hint
