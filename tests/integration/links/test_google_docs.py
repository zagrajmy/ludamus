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


def _email_form_response() -> MagicMock:
    # A form that collects respondent email and carries one mapped question, so
    # fetch_questions runs the sheet-header email-synthesis path.
    return MagicMock(
        ok=True,
        json=lambda: {
            "items": [
                {"title": "Title", "questionItem": {"question": {"textQuestion": {}}}}
            ],
            "settings": {"emailCollectionType": "RESPONDER_INPUT"},
        },
    )


def _meta_with_title(title: str = "Form Responses 1") -> MagicMock:
    return MagicMock(
        ok=True, json=lambda: {"sheets": [{"properties": {"title": title}}]}
    )


def _route_email_synthesis(*, meta: MagicMock, values: MagicMock):
    # Route the three fetch_questions calls (Forms API, sheet metadata, sheet
    # values) so the email-synthesis path's sheet-header read can be steered.
    form = _email_form_response()

    def get(url: str, **_kwargs: object) -> MagicMock:
        if url.startswith("https://forms.googleapis.com/"):
            return form
        if "/values/" in url:
            return values
        return meta

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

        result = GoogleDocsProposalImporter().fetch_questions(
            secret=SECRET, config=CONFIG
        )

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

        result = GoogleDocsProposalImporter().fetch_questions(
            secret=SECRET, config=CONFIG
        )

        assert [q.title for q in result] == ["Imię", "Wiek"]

    def test_synthesizes_email_question_from_sheet_header_at_configured_column(
        self, google
    ):
        # The auto-collected email column doesn't appear in items[]; the Forms
        # API surfaces collection state on settings.emailCollectionType. With
        # an email_column set, the importer reads the sheet header at that
        # 1-indexed column and synthesizes a SourceQuestion the recipe can map
        # to session.contact_email.
        form_response = MagicMock(
            ok=True,
            json=lambda: {
                "items": [
                    {
                        "title": "Title",
                        "questionItem": {"question": {"textQuestion": {}}},
                    }
                ],
                "settings": {"emailCollectionType": "RESPONDER_INPUT"},
            },
        )
        sheet_meta = MagicMock(
            ok=True,
            json=lambda: {"sheets": [{"properties": {"title": "Form Responses 1"}}]},
        )
        sheet_values = MagicMock(
            ok=True, json=lambda: {"values": [["Timestamp", "email-header", "Title"]]}
        )

        def get(url: str, **_kwargs: object) -> MagicMock:
            if url.startswith("https://forms.googleapis.com/"):
                return form_response
            if "/values/" in url:
                return sheet_values
            return sheet_meta

        google.session.get.side_effect = get

        result = GoogleDocsProposalImporter().fetch_questions(
            secret=SECRET, config=CONFIG, header_row=1, email_column=2
        )

        assert [q.title for q in result] == ["Title", "email-header"]
        email_question = result[-1]
        assert email_question.field_type == "text"
        assert email_question.is_multiple is False
        assert email_question.allow_custom is False

    def test_does_not_synthesize_email_when_column_not_configured(self, google):
        google.session.get.return_value = MagicMock(
            ok=True,
            json=lambda: {
                "items": [
                    {
                        "title": "Title",
                        "questionItem": {"question": {"textQuestion": {}}},
                    }
                ],
                "settings": {"emailCollectionType": "RESPONDER_INPUT"},
            },
        )

        result = GoogleDocsProposalImporter().fetch_questions(
            secret=SECRET, config=CONFIG
        )

        assert [q.title for q in result] == ["Title"]

    def test_does_not_synthesize_email_when_form_does_not_collect_email(self, google):
        google.session.get.return_value = MagicMock(
            ok=True,
            json=lambda: {
                "items": [
                    {
                        "title": "Title",
                        "questionItem": {"question": {"textQuestion": {}}},
                    }
                ],
                "settings": {"emailCollectionType": "DO_NOT_COLLECT"},
            },
        )

        result = GoogleDocsProposalImporter().fetch_questions(
            secret=SECRET, config=CONFIG, header_row=1, email_column=2
        )

        assert [q.title for q in result] == ["Title"]

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
        google.session.get.return_value = MagicMock(
            ok=True,
            json=lambda: {
                "items": [
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
            },
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

    def test_email_header_skipped_when_column_below_one(self, google):
        google.session.get.return_value = _email_form_response()

        result = GoogleDocsProposalImporter().fetch_questions(
            secret=SECRET, config=CONFIG, header_row=1, email_column=0
        )

        # An out-of-range column yields no header, so no email question.
        assert [q.title for q in result] == ["Title"]

    def test_email_header_skipped_when_responses_tab_has_no_title(self, google):
        google.session.get.side_effect = _route_email_synthesis(
            meta=MagicMock(ok=True, json=lambda: {"sheets": []}), values=MagicMock()
        )

        result = GoogleDocsProposalImporter().fetch_questions(
            secret=SECRET, config=CONFIG, header_row=1, email_column=2
        )

        assert [q.title for q in result] == ["Title"]

    def test_email_header_skipped_when_values_request_fails(self, google):
        google.session.get.side_effect = _route_email_synthesis(
            meta=_meta_with_title(), values=MagicMock(ok=False)
        )

        result = GoogleDocsProposalImporter().fetch_questions(
            secret=SECRET, config=CONFIG, header_row=1, email_column=2
        )

        assert [q.title for q in result] == ["Title"]

    def test_email_header_skipped_when_values_are_empty(self, google):
        google.session.get.side_effect = _route_email_synthesis(
            meta=_meta_with_title(),
            values=MagicMock(ok=True, json=lambda: {"values": []}),
        )

        result = GoogleDocsProposalImporter().fetch_questions(
            secret=SECRET, config=CONFIG, header_row=1, email_column=2
        )

        assert [q.title for q in result] == ["Title"]

    def test_email_header_skipped_when_column_exceeds_row_width(self, google):
        google.session.get.side_effect = _route_email_synthesis(
            meta=_meta_with_title(),
            values=MagicMock(ok=True, json=lambda: {"values": [["A"]]}),
        )

        result = GoogleDocsProposalImporter().fetch_questions(
            secret=SECRET, config=CONFIG, header_row=1, email_column=5
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
