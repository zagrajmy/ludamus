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
    SHEETS_META_URL,
    SHEETS_VALUES_URL,
    GoogleDocsProposalConfig,
    GoogleDocsProposalImporter,
)
from ludamus.pacts.chronology import CheckOutcome, SourceQuestion

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


class TestGoogleDocsProposalImporterFetchQuestions:
    def test_returns_questions_with_setup_in_form_order(self, google):
        google.session.get.return_value = MagicMock(
            ok=True,
            json=lambda: {
                "items": [
                    {
                        "title": "Imię",
                        "questionItem": {"question": {"textQuestion": {}}},
                    },
                    {"title": "Ogólne informacje"},  # section header, no question
                    {"title": "", "questionItem": {"question": {}}},  # empty title
                    {
                        "title": "Ile masz lat?",
                        "questionItem": {
                            "question": {
                                "choiceQuestion": {
                                    "type": "RADIO",
                                    "options": [
                                        {"value": "do 16"},
                                        {"value": "18+"},
                                        {"isOther": True},
                                    ],
                                }
                            }
                        },
                    },
                    {
                        "title": "Dostępność",
                        "questionItem": {
                            "question": {
                                "choiceQuestion": {
                                    "type": "CHECKBOX",
                                    "options": [{"value": "18+"}, {"value": "dzieci"}],
                                }
                            }
                        },
                    },
                ]
            },
        )

        result = GoogleDocsProposalImporter().fetch_questions(SECRET, CONFIG)

        assert result == [
            SourceQuestion(title="Imię", field_type="text"),
            SourceQuestion(
                title="Ile masz lat?",
                field_type="select",
                is_multiple=False,
                allow_custom=True,
                options=["do 16", "18+"],
            ),
            SourceQuestion(
                title="Dostępność",
                field_type="select",
                is_multiple=True,
                allow_custom=False,
                options=["18+", "dzieci"],
            ),
        ]
        google.session.get.assert_called_once_with(
            FORMS_API_URL.format(form_id="form-1"), timeout=10
        )

    def test_duplicate_titles_collapse_to_a_single_recipe_entry(self, google):
        # Two form questions with the same title produce a single recipe entry —
        # ImportSettings.questions is dict[title, target] and the mill maps the
        # cell at the title-level. ImportRow.get_value re-collapses the sheet
        # columns the same way.
        google.session.get.return_value = MagicMock(
            ok=True,
            json=lambda: {
                "items": [
                    {
                        "title": "Imię",
                        "questionItem": {"question": {"textQuestion": {}}},
                    },
                    {
                        "title": "Imię",
                        "questionItem": {"question": {"textQuestion": {}}},
                    },
                    {
                        "title": "Wiek",
                        "questionItem": {"question": {"textQuestion": {}}},
                    },
                ]
            },
        )

        result = GoogleDocsProposalImporter().fetch_questions(SECRET, CONFIG)

        assert [q.title for q in result] == ["Imię", "Wiek"]

    def test_wrong_config_type_returns_empty(self):
        assert (
            GoogleDocsProposalImporter().fetch_questions(SECRET, _OtherConfig()) == []
        )

    def test_non_ok_response_returns_empty(self, google):
        google.session.get.return_value = MagicMock(ok=False)

        assert GoogleDocsProposalImporter().fetch_questions(SECRET, CONFIG) == []

    def test_request_exception_returns_empty(self, google):
        google.session.get.side_effect = requests.RequestException("timeout")

        assert GoogleDocsProposalImporter().fetch_questions(SECRET, CONFIG) == []


def _route_get(*, values: list[list[str]], title: str = "Form Responses 1"):
    # The importer first reads spreadsheet metadata (for the tab title), then
    # the tab's values; route each call by URL so call order/count is irrelevant.
    meta = MagicMock(
        ok=True, json=lambda: {"sheets": [{"properties": {"title": title}}]}
    )
    vals = MagicMock(ok=True, json=lambda: {"values": values})

    def get(url: str, **_kwargs: object) -> MagicMock:
        return vals if "/values/" in url else meta

    return get


class TestGoogleDocsProposalImporterFetchResponses:
    def test_reads_the_whole_named_tab(self, google):
        google.session.get.side_effect = _route_get(
            values=[["Timestamp", "Title"], ["t1", "My Talk"]]
        )

        result = GoogleDocsProposalImporter().fetch_responses(SECRET, CONFIG)

        assert [r.data for r in result] == [{"Timestamp": "t1", "Title": "My Talk"}]
        google.session.get.assert_any_call(
            SHEETS_META_URL.format(sheet_id="sheet-1"), timeout=10
        )
        # The values request names the tab (URL-encoded) instead of a fixed A:Z
        # window, so every column is read no matter how wide the form is.
        google.session.get.assert_any_call(
            SHEETS_VALUES_URL.format(sheet_id="sheet-1", range="Form%20Responses%201"),
            timeout=30,
        )

    def test_reads_columns_past_z(self, google):
        headers = [f"Q{i}" for i in range(30)]
        google.session.get.side_effect = _route_get(
            values=[headers, [str(i) for i in range(30)]]
        )

        result = GoogleDocsProposalImporter().fetch_responses(SECRET, CONFIG)

        assert [r.data for r in result] == [{f"Q{i}": str(i) for i in range(30)}]

    def test_uses_the_first_tab_when_several_exist(self, google):
        meta = MagicMock(
            ok=True,
            json=lambda: {
                "sheets": [
                    {"properties": {"title": "First"}},
                    {"properties": {"title": "Second"}},
                ]
            },
        )
        vals = MagicMock(ok=True, json=lambda: {"values": [["Title"], ["My Talk"]]})
        google.session.get.side_effect = lambda url, **_: (
            vals if "/values/" in url else meta
        )

        result = GoogleDocsProposalImporter().fetch_responses(SECRET, CONFIG)

        assert [r.data for r in result] == [{"Title": "My Talk"}]
        google.session.get.assert_any_call(
            SHEETS_VALUES_URL.format(sheet_id="sheet-1", range="First"), timeout=30
        )

    def test_wrong_config_returns_empty(self):
        assert (
            GoogleDocsProposalImporter().fetch_responses(SECRET, _OtherConfig()) == []
        )

    def test_no_sheets_returns_empty(self, google):
        google.session.get.return_value = MagicMock(
            ok=True, json=lambda: {"sheets": []}
        )

        assert GoogleDocsProposalImporter().fetch_responses(SECRET, CONFIG) == []

    def test_empty_values_returns_empty(self, google):
        google.session.get.side_effect = _route_get(values=[])

        assert GoogleDocsProposalImporter().fetch_responses(SECRET, CONFIG) == []

    def test_header_row_skips_leading_rows_and_uses_named_row_as_headers(self, google):
        # Sheet has 2 banner rows before the real header. With header_row=3,
        # row 3 (1-indexed) is the headers, row 4+ are the data.
        google.session.get.side_effect = _route_get(
            values=[
                ["Banner row 1", "", ""],
                ["Banner row 2", "", ""],
                ["Timestamp", "Imię", "Wiek"],
                ["t1", "Anna", "30"],
                ["t2", "Bartek", "25"],
            ]
        )

        result = GoogleDocsProposalImporter().fetch_responses(
            SECRET, CONFIG, header_row=3
        )

        assert [r.data for r in result] == [
            {"Timestamp": "t1", "Imię": "Anna", "Wiek": "30"},
            {"Timestamp": "t2", "Imię": "Bartek", "Wiek": "25"},
        ]

    def test_header_row_out_of_range_returns_empty(self, google):
        google.session.get.side_effect = _route_get(
            values=[["Timestamp", "Imię"], ["t1", "Anna"]]
        )

        assert (
            GoogleDocsProposalImporter().fetch_responses(SECRET, CONFIG, header_row=5)
            == []
        )

    def test_header_row_below_one_returns_empty(self, google):
        google.session.get.side_effect = _route_get(
            values=[["Timestamp", "Imię"], ["t1", "Anna"]]
        )

        assert (
            GoogleDocsProposalImporter().fetch_responses(SECRET, CONFIG, header_row=0)
            == []
        )

    def test_duplicate_header_columns_get_occurrence_suffixes(self, google):
        # Sheet header "Imię" twice: without disambiguation the second column
        # silently overwrites the first; the operator-facing recipe entry for
        # "Imię" then disagrees with the actual data. The link uniquifies the
        # column keys; `ImportRow.get_value` re-collapses them downstream.
        google.session.get.side_effect = _route_get(
            values=[["Timestamp", "Imię", "Imię"], ["t1", "Anna", "Bartek"]]
        )

        result = GoogleDocsProposalImporter().fetch_responses(SECRET, CONFIG)

        assert [r.data for r in result] == [
            {"Timestamp": "t1", "Imię": "Anna", "Imię (2)": "Bartek"}
        ]
