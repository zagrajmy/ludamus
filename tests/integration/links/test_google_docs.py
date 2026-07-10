"""Integration tests for the Google Docs proposal importer and sheet writer.

`google.auth` is mocked at the package boundary (credentials + authorized
session); the importer's own `check` / `_probe` logic runs for real, so the
outcome mapping is exercised end to end.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.parse import quote

import pytest
import requests
from pydantic import BaseModel

from ludamus.links.google_docs import (
    FORMS_API_URL,
    SHEETS_API_URL,
    SHEETS_CLEAR_URL,
    SHEETS_META_URL,
    SHEETS_UPDATE_URL,
    SHEETS_VALUES_URL,
    GoogleDocsProposalConfig,
    GoogleDocsProposalImporter,
    GoogleSheetsWriter,
)
from ludamus.pacts.chronology import CheckOutcome, SourceQuestion
from ludamus.pacts.discounts import SheetExportError

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


def _meta_with_title(title: str = "Form Responses 1") -> MagicMock:
    return MagicMock(
        ok=True, json=lambda: {"sheets": [{"properties": {"title": title}}]}
    )


def _form_response(items: list[dict]) -> MagicMock:
    return MagicMock(ok=True, json=lambda: {"items": items})


def _header_values(headers: list[str]) -> MagicMock:
    return MagicMock(ok=True, json=lambda: {"values": [headers]})


def _route_questions(
    *, form: MagicMock, meta: MagicMock | None = None, values: MagicMock | None = None
):
    # Route the three fetch_questions calls (Forms API, sheet metadata, sheet
    # values) so both the form schema and the header row can be steered.
    resolved_meta = meta if meta is not None else _meta_with_title()
    resolved_values = values if values is not None else _header_values([])

    def get(url: str, **_kwargs: object) -> MagicMock:
        if url.startswith("https://forms.googleapis.com/"):
            return form
        if "/values/" in url:
            return resolved_values
        return resolved_meta

    return get


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
    def test_returns_sheet_columns_enriched_with_form_setup_in_sheet_order(
        self, google
    ):
        # The sheet's header row decides which columns exist and in what order;
        # the form only supplies the field type and options for the columns it
        # recognizes.
        google.session.get.side_effect = _route_questions(
            form=_form_response(
                [
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
            ),
            values=_header_values(["Dostępność", "Imię", "Ile masz lat?"]),
        )

        result = GoogleDocsProposalImporter().fetch_questions(
            secret=SECRET, config=CONFIG
        )

        assert result == [
            SourceQuestion(
                title="Dostępność",
                field_type="select",
                is_multiple=True,
                allow_custom=False,
                options=["18+", "dzieci"],
            ),
            SourceQuestion(title="Imię", field_type="text"),
            SourceQuestion(
                title="Ile masz lat?",
                field_type="select",
                is_multiple=False,
                allow_custom=True,
                options=["do 16", "18+"],
            ),
        ]

    def test_sheet_only_columns_become_plain_text_questions(self, google):
        # Timestamp and the auto-collected email are real sheet columns the
        # Forms API never reports. They must still reach the recipe so the
        # operator can map the email to session.contact_email.
        google.session.get.side_effect = _route_questions(
            form=_form_response(
                [{"title": "Tytuł", "questionItem": {"question": {"textQuestion": {}}}}]
            ),
            values=_header_values(["Sygnatura czasowa", "Adres e-mail", "Tytuł"]),
        )

        result = GoogleDocsProposalImporter().fetch_questions(
            secret=SECRET, config=CONFIG
        )

        assert result == [
            SourceQuestion(title="Sygnatura czasowa", field_type="text"),
            SourceQuestion(title="Adres e-mail", field_type="text"),
            SourceQuestion(title="Tytuł", field_type="text"),
        ]

    def test_blank_and_repeated_headers_collapse_to_one_entry_each(self, google):
        # ImportSettings.questions is dict[title, target] and ImportRow matches a
        # bare header against every " (2)"-suffixed column, so one entry already
        # addresses them all. A blank cell names no column.
        google.session.get.side_effect = _route_questions(
            form=_form_response(
                [{"title": "Imię", "questionItem": {"question": {"textQuestion": {}}}}]
            ),
            values=_header_values(["Imię", "", "Imię", "Wiek"]),
        )

        result = GoogleDocsProposalImporter().fetch_questions(
            secret=SECRET, config=CONFIG
        )

        assert [q.title for q in result] == ["Imię", "Wiek"]

    def test_falls_back_to_form_questions_when_the_sheet_read_fails(self, google):
        # A transient Sheets outage must not blank the whole recipe.
        google.session.get.side_effect = _route_questions(
            form=_form_response(
                [
                    {
                        "title": "Imię",
                        "questionItem": {"question": {"textQuestion": {}}},
                    },
                    {
                        "title": "Wiek",
                        "questionItem": {"question": {"textQuestion": {}}},
                    },
                ]
            ),
            values=MagicMock(ok=False),
        )

        result = GoogleDocsProposalImporter().fetch_questions(
            secret=SECRET, config=CONFIG
        )

        assert [q.title for q in result] == ["Imię", "Wiek"]

    def test_duplicate_titles_collapse_to_a_single_recipe_entry(self, google):
        # Two form questions with the same title produce a single recipe entry —
        # ImportSettings.questions is dict[title, target] and the mill maps the
        # cell at the title-level. ImportRow.get_value re-collapses the sheet
        # columns the same way.
        google.session.get.side_effect = _route_questions(
            form=_form_response(
                [
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
            ),
            values=_header_values(["Imię", "Wiek"]),
        )

        result = GoogleDocsProposalImporter().fetch_questions(
            secret=SECRET, config=CONFIG
        )

        assert [q.title for q in result] == ["Imię", "Wiek"]

    def test_wrong_config_type_returns_empty(self):
        assert not GoogleDocsProposalImporter().fetch_questions(
            secret=SECRET, config=_OtherConfig()
        )

    def test_invalid_credentials_returns_empty(self):
        # An empty secret trips _CredentialsError inside _session.
        assert not GoogleDocsProposalImporter().fetch_questions(
            secret=b"", config=CONFIG
        )

    def test_non_ok_response_returns_empty(self, google):
        google.session.get.return_value = MagicMock(ok=False)

        assert not GoogleDocsProposalImporter().fetch_questions(
            secret=SECRET, config=CONFIG
        )

    def test_request_exception_returns_empty(self, google):
        google.session.get.side_effect = requests.RequestException("timeout")

        assert not GoogleDocsProposalImporter().fetch_questions(
            secret=SECRET, config=CONFIG
        )

    def test_duplicate_titles_with_different_types_raise(self, google):
        google.session.get.return_value = MagicMock(
            ok=True,
            json=lambda: {
                "items": [
                    {"title": "Q", "questionItem": {"question": {"textQuestion": {}}}},
                    {
                        "title": "Q",
                        "questionItem": {
                            "question": {
                                "choiceQuestion": {
                                    "type": "RADIO",
                                    "options": [{"value": "a"}],
                                }
                            }
                        },
                    },
                ]
            },
        )

        with pytest.raises(ValueError, match="Duplicate questions!"):
            GoogleDocsProposalImporter().fetch_questions(secret=SECRET, config=CONFIG)

    def test_duplicate_select_titles_merge_their_setup(self, google):
        # Same title, both select: the second occurrence folds into the first —
        # multiple/allow_custom OR together, options become the deduped union.
        google.session.get.side_effect = _route_questions(
            form=_form_response(
                [
                    {
                        "title": "Q",
                        "questionItem": {
                            "question": {
                                "choiceQuestion": {
                                    "type": "RADIO",
                                    "options": [{"value": "a"}, {"value": "b"}],
                                }
                            }
                        },
                    },
                    {
                        "title": "Q",
                        "questionItem": {
                            "question": {
                                "choiceQuestion": {
                                    "type": "CHECKBOX",
                                    "options": [
                                        {"value": "b"},
                                        {"value": "c"},
                                        {"isOther": True},
                                    ],
                                }
                            }
                        },
                    },
                ]
            ),
            values=_header_values(["Q"]),
        )

        result = GoogleDocsProposalImporter().fetch_questions(
            secret=SECRET, config=CONFIG
        )

        assert result == [
            SourceQuestion(
                title="Q",
                field_type="select",
                is_multiple=True,
                allow_custom=True,
                options=["a", "b", "c"],
            )
        ]

    def test_falls_back_to_form_questions_when_responses_tab_has_no_title(self, google):
        google.session.get.side_effect = _route_questions(
            form=_form_response(
                [{"title": "Title", "questionItem": {"question": {"textQuestion": {}}}}]
            ),
            meta=MagicMock(ok=True, json=lambda: {"sheets": []}),
        )

        result = GoogleDocsProposalImporter().fetch_questions(
            secret=SECRET, config=CONFIG
        )

        assert [q.title for q in result] == ["Title"]


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


class TestGoogleDocsProposalImporterFetchHeaders:
    def test_returns_the_configured_header_row_including_metadata_columns(self, google):
        google.session.get.side_effect = _route_get(
            values=[["Sygnatura czasowa", "Adres e-mail", "Tytuł"], ["a", "b", "c"]]
        )

        result = GoogleDocsProposalImporter().fetch_headers(
            secret=SECRET, config=CONFIG, header_row=1
        )

        assert result == ["Sygnatura czasowa", "Adres e-mail", "Tytuł"]

    def test_reads_the_named_row_not_the_first(self, google):
        google.session.get.side_effect = _route_get(values=[["Real", "Headers"]])

        GoogleDocsProposalImporter().fetch_headers(
            secret=SECRET, config=CONFIG, header_row=3
        )

        values_url = next(
            call.args[0]
            for call in google.session.get.call_args_list
            if "/values/" in call.args[0]
        )
        assert quote("Form Responses 1!3:3", safe="") in values_url

    def test_repeated_and_blank_headers_collapse(self, google):
        # ImportRow matches a bare header against every " (2)"-suffixed column,
        # so one entry addresses them all; a blank cell names no column.
        google.session.get.side_effect = _route_get(
            values=[["Dur", "", "Dur", " Dur ", "Tytuł"]]
        )

        result = GoogleDocsProposalImporter().fetch_headers(
            secret=SECRET, config=CONFIG, header_row=1
        )

        assert result == ["Dur", "Tytuł"]

    def test_wrong_config_returns_empty(self):
        result = GoogleDocsProposalImporter().fetch_headers(
            secret=SECRET, config=_OtherConfig(), header_row=1
        )

        assert not result

    def test_header_row_below_one_returns_empty(self, google):
        result = GoogleDocsProposalImporter().fetch_headers(
            secret=SECRET, config=CONFIG, header_row=0
        )

        assert not result
        assert google.session.get.call_count == 0

    def test_no_sheets_returns_empty(self, google):
        google.session.get.return_value = MagicMock(
            ok=True, json=lambda: {"sheets": []}
        )

        result = GoogleDocsProposalImporter().fetch_headers(
            secret=SECRET, config=CONFIG, header_row=1
        )

        assert not result

    def test_non_ok_values_response_returns_empty(self, google):
        failing_values = MagicMock(ok=False)
        google.session.get.side_effect = lambda url, **_kwargs: (
            failing_values if "/values/" in url else _meta_with_title()
        )

        result = GoogleDocsProposalImporter().fetch_headers(
            secret=SECRET, config=CONFIG, header_row=1
        )

        assert not result

    def test_empty_values_returns_empty(self, google):
        google.session.get.side_effect = _route_get(values=[])

        result = GoogleDocsProposalImporter().fetch_headers(
            secret=SECRET, config=CONFIG, header_row=1
        )

        assert not result


class TestGoogleDocsProposalImporterFetchResponses:
    def test_reads_the_whole_named_tab(self, google):
        google.session.get.side_effect = _route_get(
            values=[["Timestamp", "Title"], ["t1", "My Talk"]]
        )

        result = GoogleDocsProposalImporter().fetch_responses(
            secret=SECRET, config=CONFIG
        )

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

        result = GoogleDocsProposalImporter().fetch_responses(
            secret=SECRET, config=CONFIG
        )

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

        result = GoogleDocsProposalImporter().fetch_responses(
            secret=SECRET, config=CONFIG
        )

        assert [r.data for r in result] == [{"Title": "My Talk"}]
        google.session.get.assert_any_call(
            SHEETS_VALUES_URL.format(sheet_id="sheet-1", range="First"), timeout=30
        )

    def test_wrong_config_returns_empty(self):
        assert (
            GoogleDocsProposalImporter().fetch_responses(
                secret=SECRET, config=_OtherConfig()
            )
            == []
        )

    def test_no_sheets_returns_empty(self, google):
        google.session.get.return_value = MagicMock(
            ok=True, json=lambda: {"sheets": []}
        )

        assert (
            GoogleDocsProposalImporter().fetch_responses(secret=SECRET, config=CONFIG)
            == []
        )

    def test_empty_values_returns_empty(self, google):
        google.session.get.side_effect = _route_get(values=[])

        assert (
            GoogleDocsProposalImporter().fetch_responses(secret=SECRET, config=CONFIG)
            == []
        )

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
            secret=SECRET, config=CONFIG, header_row=3
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
            GoogleDocsProposalImporter().fetch_responses(
                secret=SECRET, config=CONFIG, header_row=5
            )
            == []
        )

    def test_header_row_below_one_returns_empty(self, google):
        google.session.get.side_effect = _route_get(
            values=[["Timestamp", "Imię"], ["t1", "Anna"]]
        )

        assert (
            GoogleDocsProposalImporter().fetch_responses(
                secret=SECRET, config=CONFIG, header_row=0
            )
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

        result = GoogleDocsProposalImporter().fetch_responses(
            secret=SECRET, config=CONFIG
        )

        assert [r.data for r in result] == [
            {"Timestamp": "t1", "Imię": "Anna", "Imię (2)": "Bartek"}
        ]

    def test_invalid_credentials_returns_empty(self):
        # An empty secret trips _CredentialsError inside _session.
        assert (
            GoogleDocsProposalImporter().fetch_responses(secret=b"", config=CONFIG)
            == []
        )

    def test_non_ok_values_response_returns_empty(self, google):
        def get(url: str, **_kwargs: object) -> MagicMock:
            if "/values/" in url:
                return MagicMock(ok=False)
            return _meta_with_title()

        google.session.get.side_effect = get

        assert (
            GoogleDocsProposalImporter().fetch_responses(secret=SECRET, config=CONFIG)
            == []
        )

    def test_non_ok_metadata_response_returns_empty(self, google):
        google.session.get.return_value = MagicMock(ok=False)

        assert (
            GoogleDocsProposalImporter().fetch_responses(secret=SECRET, config=CONFIG)
            == []
        )


EXPORT_ROWS = [["Creator", "Accreditation type"], ["Alice", "Guest"]]
_METADATA_AND_ROW_COUNT_GETS = 2


def _writer_get(*, meta: MagicMock, old_row_count: int = 0):
    row_values = MagicMock(ok=True, json=lambda: {"values": [["x"]] * old_row_count})

    def get(url: str, **_kwargs: object) -> MagicMock:
        if "A%3AA" in url:
            return row_values
        return meta

    return get


class TestGoogleSheetsWriter:
    def test_writes_the_first_tab_without_clearing_when_not_shrinking(self, google):
        google.session.get.side_effect = _writer_get(
            meta=_meta_with_title(), old_row_count=len(EXPORT_ROWS)
        )
        google.session.put.return_value = _resp(ok=True)

        GoogleSheetsWriter().write_rows(
            secret=SECRET, spreadsheet_id="sheet-1", rows=EXPORT_ROWS
        )

        google.creds.assert_called_once_with(
            {"type": "service_account"},
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        assert google.session.get.call_count == _METADATA_AND_ROW_COUNT_GETS
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

    def test_clears_trailing_rows_when_new_export_is_shorter(self, google):
        google.session.get.side_effect = _writer_get(
            meta=_meta_with_title(), old_row_count=5
        )
        google.session.post.return_value = _resp(ok=True)
        google.session.put.return_value = _resp(ok=True)

        GoogleSheetsWriter().write_rows(
            secret=SECRET, spreadsheet_id="sheet-1", rows=EXPORT_ROWS
        )

        google.session.post.assert_called_once_with(
            SHEETS_CLEAR_URL.format(
                sheet_id="sheet-1", range="%27Form%20Responses%201%27%21A3%3AZZ5"
            ),
            timeout=30,
        )

    def test_quotes_tab_title_that_looks_like_a_cell_reference(self, google):
        google.session.get.side_effect = _writer_get(
            meta=_meta_with_title("A1"), old_row_count=5
        )
        google.session.post.return_value = _resp(ok=True)
        google.session.put.return_value = _resp(ok=True)

        GoogleSheetsWriter().write_rows(
            secret=SECRET, spreadsheet_id="sheet-1", rows=EXPORT_ROWS
        )

        google.session.post.assert_called_once_with(
            SHEETS_CLEAR_URL.format(sheet_id="sheet-1", range="%27A1%27%21A3%3AZZ5"),
            timeout=30,
        )

    def test_quotes_apostrophe_in_tab_title(self, google):
        google.session.get.side_effect = _writer_get(
            meta=_meta_with_title("It's"), old_row_count=5
        )
        google.session.post.return_value = _resp(ok=True)
        google.session.put.return_value = _resp(ok=True)

        GoogleSheetsWriter().write_rows(
            secret=SECRET, spreadsheet_id="sheet-1", rows=EXPORT_ROWS
        )

        google.session.post.assert_called_once_with(
            SHEETS_CLEAR_URL.format(
                sheet_id="sheet-1", range="%27It%27%27s%27%21A3%3AZZ5"
            ),
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

    def test_clear_trailing_failure_raises_after_write(self, google):
        google.session.get.side_effect = _writer_get(
            meta=_meta_with_title(), old_row_count=5
        )
        google.session.put.return_value = _resp(ok=True)
        google.session.post.return_value = _resp(
            ok=False, status_code=403, text="no edit"
        )

        with pytest.raises(
            SheetExportError,
            match="Spreadsheet clear trailing rows request failed with 403: no edit",
        ):
            GoogleSheetsWriter().write_rows(
                secret=SECRET, spreadsheet_id="sheet-1", rows=EXPORT_ROWS
            )

        google.session.put.assert_called_once()

    def test_write_failure_raises_without_clearing(self, google):
        google.session.get.side_effect = _writer_get(
            meta=_meta_with_title(), old_row_count=5
        )
        google.session.put.return_value = _resp(ok=False, status_code=500, text="boom")

        with pytest.raises(
            SheetExportError, match="Spreadsheet write request failed with 500: boom"
        ):
            GoogleSheetsWriter().write_rows(
                secret=SECRET, spreadsheet_id="sheet-1", rows=EXPORT_ROWS
            )

        google.session.post.assert_not_called()

    def test_request_exception_raises(self, google):
        google.session.get.side_effect = _writer_get(
            meta=_meta_with_title(), old_row_count=5
        )
        google.session.put.return_value = _resp(ok=True)
        google.session.post.side_effect = requests.RequestException("timeout")

        with pytest.raises(
            SheetExportError,
            match="Spreadsheet clear trailing rows request failed: timeout",
        ):
            GoogleSheetsWriter().write_rows(
                secret=SECRET, spreadsheet_id="sheet-1", rows=EXPORT_ROWS
            )
