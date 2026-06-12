"""Integration tests for the Google Docs Import panel section.

Import lives in its own section, not under integrations settings; the
integration is just the connection it pulls through.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest
from django.contrib import messages
from django.urls import reverse
from django.utils.timezone import get_current_timezone, localtime

from ludamus.adapters.db.django.models import (
    EventIntegration,
    Facilitator,
    HostPersonalData,
    ImportLogEntry,
    PersonalDataField,
    ProposalCategory,
    Session,
    SessionField,
    SessionFieldOption,
    SessionFieldValue,
    TimeSlot,
    Track,
)
from ludamus.gates.web.django.chronology.panel.views.base import import_tab_urls
from ludamus.pacts import EventDTO
from ludamus.pacts.chronology import (
    EventIntegrationDTO,
    IntegrationImplementationId,
    IntegrationKind,
)
from ludamus.pacts.submissions import EntityRef, ImportSettings, TimeSlotSpec
from tests.integration.conftest import EventFactory
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."
IMPL = IntegrationImplementationId.GOOGLE_PROPOSAL_PULLER
CONFIG_JSON = json.dumps({"sheet_id": "sheet-1", "form_id": "form-1"})
EMPTY_STATS = {
    "hosts_count": 0,
    "pending_proposals": 0,
    "rooms_count": 0,
    "scheduled_sessions": 0,
    "total_proposals": 0,
    "total_sessions": 0,
}


def _import_url(event) -> str:
    return reverse("panel:import", kwargs={"slug": event.slug})


def _tab_url(event, integration) -> str:
    return reverse(
        "panel:import-integration", kwargs={"slug": event.slug, "pk": integration.pk}
    )


def _review_url(event, integration) -> str:
    return reverse(
        "panel:import-review", kwargs={"slug": event.slug, "pk": integration.pk}
    )


def _row_save_url(event, integration) -> str:
    return reverse(
        "panel:import-row-save", kwargs={"slug": event.slug, "pk": integration.pk}
    )


def _run_url(event, integration) -> str:
    return reverse(
        "panel:import-run-do", kwargs={"slug": event.slug, "pk": integration.pk}
    )


def _test_url(event, integration) -> str:
    return reverse(
        "panel:import-test-do", kwargs={"slug": event.slug, "pk": integration.pk}
    )


def _run_page_url(event, integration) -> str:
    return reverse(
        "panel:import-run", kwargs={"slug": event.slug, "pk": integration.pk}
    )


def _log_url(event, integration) -> str:
    return reverse(
        "panel:import-log", kwargs={"slug": event.slug, "pk": integration.pk}
    )


def _log_retry_url(event, integration) -> str:
    return reverse(
        "panel:import-log-retry", kwargs={"slug": event.slug, "pk": integration.pk}
    )


def _log_reimport_url(event, integration) -> str:
    return reverse(
        "panel:import-log-reimport", kwargs={"slug": event.slug, "pk": integration.pk}
    )


def _json_url(event, integration) -> str:
    return reverse(
        "panel:import-json", kwargs={"slug": event.slug, "pk": integration.pk}
    )


def _event_context(event) -> dict[str, object]:
    return {
        "current_event": EventDTO.model_validate(event),
        "events": [EventDTO.model_validate(event)],
        "is_proposal_active": False,
        "stats": EMPTY_STATS,
    }


def _make_import_integration(event, connection, *, display_name: str):
    return EventIntegration.objects.create(
        event=event,
        kind=IntegrationKind.IMPORT.value,
        implementation=IMPL.value,
        connection=connection,
        display_name=display_name,
        config_json=CONFIG_JSON,
    )


def _dto(integration) -> EventIntegrationDTO:
    return EventIntegrationDTO(
        pk=integration.pk,
        event_id=integration.event_id,
        kind=IntegrationKind(integration.kind),
        implementation=IntegrationImplementationId(integration.implementation),
        connection_id=integration.connection_id,
        connection_display_name=integration.connection.display_name,
        display_name=integration.display_name,
        config_json=integration.config_json,
        settings_json=integration.settings_json,
        questions_snapshot_json=integration.questions_snapshot_json or "[]",
    )


def _sheets_get(values, *, title="Form Responses 1"):
    # fetch_responses reads spreadsheet metadata (tab title) then the tab's
    # values; route each Google call by URL so call order/count is irrelevant.
    meta = MagicMock(
        ok=True, json=lambda: {"sheets": [{"properties": {"title": title}}]}
    )
    vals = MagicMock(ok=True, json=lambda: {"values": values})
    return lambda url, **_: vals if "/values/" in url else meta


@pytest.mark.django_db
class TestEventImportProposalView:
    def test_get_redirects_anonymous(self, client, event):
        url = _import_url(event)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_get_redirects_non_manager(self, authenticated_client, event):
        response = authenticated_client.get(_import_url(event))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_get_renders_empty_state_without_import_integrations(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(_import_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/import.html",
            context_data=_event_context(event)
            | {"active_nav": "import", "active_integration": None},
        )

    def test_get_renders_summary_table(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.return_value = MagicMock(
                ok=True,
                json=lambda: {
                    "items": [
                        {"title": "Title", "questionItem": {"question": {}}},
                        {"title": "Section header"},
                        {"title": "System", "questionItem": {"question": {}}},
                    ]
                },
            )
            response = authenticated_client.get(_tab_url(event, integration))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/import.html",
            context_data=_event_context(event)
            | {
                "active_nav": "import",
                "active_integration": _dto(integration),
                "active_tab": "proposal",
                "tab_urls": import_tab_urls(event.slug, integration.pk),
                "summary_rows": [
                    {
                        "index": 0,
                        "status": "unconfirmed",
                        "question": "Title",
                        "mapping": "",
                        "details": "",
                    },
                    {
                        "index": 1,
                        "status": "unconfirmed",
                        "question": "System",
                        "mapping": "",
                        "details": "",
                    },
                ],
                "email_column_missing": True,
            },
        )
        # The Edit action column links each row to the Review tab.
        body = response.content.decode()
        assert _review_url(event, integration) + "?edit=0" in body
        assert _review_url(event, integration) + "?edit=1" in body

    def test_get_prefills_new_field_setup_from_a_choice_question(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.return_value = MagicMock(
                ok=True,
                json=lambda: {
                    "items": [
                        {
                            "title": "Wiek",
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
                        }
                    ]
                },
            )
            response = authenticated_client.get(_review_url(event, integration))

        assert response.status_code == HTTPStatus.OK
        assert response.context_data["rows"] == [
            {
                "index": 0,
                "question": "Wiek",
                "selected": "session-field",
                "confirmed": False,
                "field_name": "Wiek",
                "field_slug": "wiek",
                "field_type": "select",
                "is_multiple": False,
                "allow_custom": True,
                "options": "do 16\n18+",
                "option_windows": [
                    {"option": "do 16", "windows": [{"start": "", "end": ""}]},
                    {"option": "18+", "windows": [{"start": "", "end": ""}]},
                ],
                "option_entities": [
                    {"option": "do 16", "name": "do 16", "slug": "do-16"},
                    {"option": "18+", "name": "18+", "slug": "18"},
                ],
                "option_durations": [
                    {"option": "do 16", "iso": ""},
                    {"option": "18+", "iso": ""},
                ],
                "overrides": [{"raw": "", "replacement": ""}],
                "catchall_name": "",
                "catchall_slug": "",
            }
        ]
        # The source options reach the rendered setup textarea (not just context).
        assert "do 16\n18+" in response.content.decode()

    def test_review_renders_time_slot_windows_for_a_checkbox_question(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        integration.settings_json = json.dumps(
            {
                "questions": {
                    "When": {
                        "to": "session.time_slots",
                        "values": {
                            "Fri": {
                                "to": "time_slot",
                                "start_time": "2025-09-19T16:00:00+02:00",
                                "end_time": "2025-09-19T22:00:00+02:00",
                            }
                        },
                    }
                }
            }
        )
        integration.save(update_fields=["settings_json"])

        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.return_value = MagicMock(
                ok=True,
                json=lambda: {
                    "items": [
                        {
                            "title": "When",
                            "questionItem": {
                                "question": {
                                    "choiceQuestion": {
                                        "type": "CHECKBOX",
                                        "options": [{"value": "Fri"}, {"value": "Sat"}],
                                    }
                                }
                            },
                        }
                    ]
                },
            )
            response = authenticated_client.get(_review_url(event, integration))

        assert response.status_code == HTTPStatus.OK
        fri_start = localtime(
            datetime.fromisoformat("2025-09-19T16:00:00+02:00")
        ).strftime("%Y-%m-%dT%H:%M")
        fri_end = localtime(
            datetime.fromisoformat("2025-09-19T22:00:00+02:00")
        ).strftime("%Y-%m-%dT%H:%M")
        row = response.context_data["rows"][0]
        assert row["selected"] == "session.time_slots"
        assert row["option_windows"] == [
            {"option": "Fri", "windows": [{"start": fri_start, "end": fri_end}]},
            {"option": "Sat", "windows": [{"start": "", "end": ""}]},
        ]

    def test_review_renders_track_entities_for_a_choice_question(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        integration.settings_json = json.dumps(
            {
                "questions": {
                    "Suggested": {
                        "to": "track",
                        "values": {"RPG": {"name": "RPG sessions", "slug": "rpg"}},
                        "catchall": {"name": "Other", "slug": "other"},
                    }
                }
            }
        )
        integration.save(update_fields=["settings_json"])

        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.return_value = MagicMock(
                ok=True,
                json=lambda: {
                    "items": [
                        {
                            "title": "Suggested",
                            "questionItem": {
                                "question": {
                                    "choiceQuestion": {
                                        "type": "RADIO",
                                        "options": [
                                            {"value": "RPG"},
                                            {"value": "LARP"},
                                        ],
                                    }
                                }
                            },
                        }
                    ]
                },
            )
            response = authenticated_client.get(_review_url(event, integration))

        assert response.status_code == HTTPStatus.OK
        row = response.context_data["rows"][0]
        assert row["selected"] == "track"
        # The configured option keeps its entity; an unconfigured one defaults to
        # the option text and its slug.
        assert row["option_entities"] == [
            {"option": "RPG", "name": "RPG sessions", "slug": "rpg"},
            {"option": "LARP", "name": "LARP", "slug": "larp"},
        ]
        assert row["catchall_name"] == "Other"
        assert row["catchall_slug"] == "other"

    def test_get_uses_cached_snapshot_when_available(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        integration.questions_snapshot_json = json.dumps(
            [
                {"title": "Cached", "field_type": "text"},
                {"title": "Also cached", "field_type": "text"},
            ]
        )
        integration.save(update_fields=["questions_snapshot_json"])

        with patch("ludamus.links.google_docs.AuthorizedSession") as session_cls:
            response = authenticated_client.get(_tab_url(event, integration))

        assert response.status_code == HTTPStatus.OK
        # Google Forms API is not called — the snapshot served the view.
        assert not session_cls.return_value.get.called
        assert [r["question"] for r in response.context_data["summary_rows"]] == [
            "Cached",
            "Also cached",
        ]

    def test_get_summary_reflects_confirmed_ignored_and_unconfirmed(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        integration.settings_json = json.dumps(
            {
                "questions": {
                    "Title": {"to": "session.title", "confirmed": True},
                    "Skip": {"ignore": True},
                    "Suggested": {
                        "to": "track",
                        "values": {"RPG": {"name": "RPG", "slug": "rpg"}},
                    },
                },
                "definitions": {
                    "session_fields": {
                        "system": {
                            "name": "System",
                            "type": "select",
                            "options": ["D&D", "Warhammer"],
                        }
                    }
                },
            }
        )
        integration.save(update_fields=["settings_json"])

        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.return_value = MagicMock(
                ok=True,
                json=lambda: {
                    "items": [
                        {"title": "Title", "questionItem": {"question": {}}},
                        {"title": "Skip", "questionItem": {"question": {}}},
                        {
                            "title": "Suggested",
                            "questionItem": {
                                "question": {
                                    "choiceQuestion": {
                                        "type": "RADIO",
                                        "options": [
                                            {"value": "RPG"},
                                            {"value": "LARP"},
                                        ],
                                    }
                                }
                            },
                        },
                        {"title": "Drifting", "questionItem": {"question": {}}},
                    ]
                },
            )
            response = authenticated_client.get(_tab_url(event, integration))

        assert response.status_code == HTTPStatus.OK
        assert response.context_data["summary_rows"] == [
            {
                "index": 0,
                "status": "confirmed",
                "question": "Title",
                "mapping": "Proposal — Title",
                "details": "",
            },
            {
                "index": 1,
                "status": "ignored",
                "question": "Skip",
                "mapping": "Don't import",
                "details": "",
            },
            {
                "index": 2,
                "status": "unconfirmed",
                "question": "Suggested",
                "mapping": "Track",
                "details": "1 mappings",
            },
            {
                "index": 3,
                "status": "unconfirmed",
                "question": "Drifting",
                "mapping": "",
                "details": "",
            },
        ]
        # The confirmed glyph reaches the rendered summary table.
        body = response.content.decode()
        assert 'data-summary-row="0"' in body

    def test_get_with_edit_query_renders_a_single_row_editor(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.return_value = MagicMock(
                ok=True,
                json=lambda: {
                    "items": [
                        {"title": "Title", "questionItem": {"question": {}}},
                        {"title": "System", "questionItem": {"question": {}}},
                    ]
                },
            )
            response = authenticated_client.get(
                _review_url(event, integration) + "?edit=1"
            )

        assert response.status_code == HTTPStatus.OK
        edit_row = response.context_data["edit_row"]
        assert edit_row is not None
        assert edit_row["index"] == 1
        assert edit_row["question"] == "System"
        edit_nav = response.context_data["edit_nav"]
        assert edit_nav == {
            "index": 1,
            "total": 2,
            "position": 2,
            "prev_index": 0,
            "next_index": None,
            "options": [
                {"index": 0, "question": "Title"},
                {"index": 1, "question": "System"},
            ],
        }
        body = response.content.decode()
        # Only the System editor is in the body — the summary table lives on
        # the Proposal tab now, not here.
        assert 'name="question_1"' in body
        assert "data-summary-row=" not in body
        # The nav renders Back-to-summary + Save + dropdown lands on this row.
        assert "Back to summary" in body
        assert "Save" in body
        assert 'value="1"' in body

    def test_get_with_hx_request_renders_only_the_swappable_region(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.return_value = MagicMock(
                ok=True,
                json=lambda: {
                    "items": [
                        {"title": "Title", "questionItem": {"question": {}}},
                        {"title": "System", "questionItem": {"question": {}}},
                    ]
                },
            )
            response = authenticated_client.get(
                _review_url(event, integration) + "?edit=1",
                headers={"HX-Request": "true"},
            )

        assert response.status_code == HTTPStatus.OK
        assert response.template_name == "panel/parts/import-review-region.html"
        body = response.content.decode()
        # The partial response carries just the editor and the nav, no chrome.
        assert 'name="question_1"' in body
        assert "Back to summary" in body
        assert "<html" not in body
        # The swap target wrapper lives in the parent template, not the partial.
        assert 'id="import-review-region"' not in body

    def test_edit_nav_disables_prev_at_first_question(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.return_value = MagicMock(
                ok=True,
                json=lambda: {
                    "items": [
                        {"title": "First", "questionItem": {"question": {}}},
                        {"title": "Second", "questionItem": {"question": {}}},
                    ]
                },
            )
            response = authenticated_client.get(
                _review_url(event, integration) + "?edit=0"
            )

        assert response.status_code == HTTPStatus.OK
        assert response.context_data["edit_nav"] == {
            "index": 0,
            "total": 2,
            "position": 1,
            "prev_index": None,
            "next_index": 1,
            "options": [
                {"index": 0, "question": "First"},
                {"index": 1, "question": "Second"},
            ],
        }

    def test_review_with_invalid_edit_query_falls_back_to_first_row(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.return_value = MagicMock(
                ok=True,
                json=lambda: {
                    "items": [{"title": "Title", "questionItem": {"question": {}}}]
                },
            )
            for raw in ("99", "abc", "-1"):
                response = authenticated_client.get(
                    _review_url(event, integration) + f"?edit={raw}"
                )
                assert response.status_code == HTTPStatus.OK, raw
                edit_row = response.context_data["edit_row"]
                assert edit_row is not None, raw
                assert edit_row["index"] == 0, raw

    def test_review_without_edit_query_lands_on_the_first_row(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.return_value = MagicMock(
                ok=True,
                json=lambda: {
                    "items": [
                        {"title": "Alpha", "questionItem": {"question": {}}},
                        {"title": "Beta", "questionItem": {"question": {}}},
                    ]
                },
            )
            response = authenticated_client.get(_review_url(event, integration))

        assert response.status_code == HTTPStatus.OK
        edit_row = response.context_data["edit_row"]
        assert edit_row is not None
        assert edit_row["index"] == 0
        assert edit_row["question"] == "Alpha"

    def test_get_without_pk_defaults_to_first_integration(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.return_value = MagicMock(
                ok=True,
                json=lambda: {
                    "items": [{"title": "Title", "questionItem": {"question": {}}}]
                },
            )
            response = authenticated_client.get(_import_url(event))

        assert response.status_code == HTTPStatus.OK
        assert response.context_data["active_integration"] == _dto(integration)

    def test_get_unknown_integration_redirects_to_section(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        _make_import_integration(event, connection_with_secret, display_name="Puller")

        response = authenticated_client.get(
            reverse(
                "panel:import-integration", kwargs={"slug": event.slug, "pk": 99999}
            )
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_import_url(event),
            messages=[(messages.ERROR, "Import integration not found.")],
        )


@pytest.mark.django_db
class TestEventImportRowSaveView:
    def test_post_redirects_non_manager(
        self, authenticated_client, event, connection_with_secret
    ):
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        response = authenticated_client.post(
            _row_save_url(event, integration),
            data={"index": "0", "question_0": "Title", "target_0": "session.title"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_post_saves_a_session_field_and_marks_confirmed(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        response = authenticated_client.post(
            _row_save_url(event, integration),
            data={
                "index": "0",
                "question_0": "System",
                "target_0": "session-field",
                "newname_0": "System",
                "fieldtype_0": "select",
                "options_0": "D&D\nWarhammer",
                "multiple_0": "on",
                "allowcustom_0": "on",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_tab_url(event, integration),
            messages=[(messages.SUCCESS, "Question saved.")],
        )
        integration.refresh_from_db()
        settings = ImportSettings.model_validate_json(integration.settings_json)
        target = settings.questions["System"]
        assert target.to == "field.system"
        assert target.confirmed is True
        definition = settings.definitions.session_fields["system"]
        assert definition.name == "System"
        assert definition.type == "select"
        assert definition.multiple is True
        assert definition.allow_custom is True
        assert definition.options == ["D&D", "Warhammer"]

    def test_post_with_stay_redirects_back_to_the_same_edit_view(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        # Operator is iterating on overrides for one question and wants to
        # stay on the same edit view after saving instead of jumping to the
        # next one.
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        response = authenticated_client.post(
            _row_save_url(event, integration),
            data={
                "index": "2",
                "question_2": "Title",
                "target_2": "session.title",
                "stay": "1",
            },
        )

        review_url = reverse(
            "panel:import-review", kwargs={"slug": event.slug, "pk": integration.pk}
        )
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=f"{review_url}?edit=2",
            messages=[(messages.SUCCESS, "Question saved.")],
        )

    def test_post_saves_time_slot_windows_for_one_row(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        response = authenticated_client.post(
            _row_save_url(event, integration),
            data={
                "index": "0",
                "question_0": "When",
                "target_0": "session.time_slots",
                "tsoption_0": ["Fri", "All", "All"],
                "tsstart_0": [
                    "2025-09-19T16:00",
                    "2025-09-19T16:00",
                    "2025-09-20T10:00",
                ],
                "tsend_0": ["2025-09-19T22:00", "2025-09-19T22:00", "2025-09-20T14:00"],
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_tab_url(event, integration),
            messages=[(messages.SUCCESS, "Question saved.")],
        )
        tz = get_current_timezone()
        integration.refresh_from_db()
        target = ImportSettings.model_validate_json(
            integration.settings_json
        ).questions["When"]
        assert target.to == "session.time_slots"
        assert target.confirmed is True
        assert target.values == {
            "Fri": TimeSlotSpec(
                start_time=datetime(2025, 9, 19, 16, 0, tzinfo=tz),
                end_time=datetime(2025, 9, 19, 22, 0, tzinfo=tz),
            ),
            "All": [
                TimeSlotSpec(
                    start_time=datetime(2025, 9, 19, 16, 0, tzinfo=tz),
                    end_time=datetime(2025, 9, 19, 22, 0, tzinfo=tz),
                ),
                TimeSlotSpec(
                    start_time=datetime(2025, 9, 20, 10, 0, tzinfo=tz),
                    end_time=datetime(2025, 9, 20, 14, 0, tzinfo=tz),
                ),
            ],
        }

    def test_post_skips_time_slot_rows_with_malformed_datetimes(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        response = authenticated_client.post(
            _row_save_url(event, integration),
            data={
                "index": "0",
                "question_0": "When",
                "target_0": "session.time_slots",
                "tsoption_0": ["Fri", "Sat"],
                "tsstart_0": ["not-a-date", "2025-09-20T10:00"],
                "tsend_0": ["2025-09-19T22:00", "2025-09-20T14:00"],
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_tab_url(event, integration),
            messages=[(messages.SUCCESS, "Question saved.")],
        )
        tz = get_current_timezone()
        integration.refresh_from_db()
        target = ImportSettings.model_validate_json(
            integration.settings_json
        ).questions["When"]
        assert target.values == {
            "Sat": TimeSlotSpec(
                start_time=datetime(2025, 9, 20, 10, 0, tzinfo=tz),
                end_time=datetime(2025, 9, 20, 14, 0, tzinfo=tz),
            )
        }

    def test_post_saves_track_target_with_catchall(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        response = authenticated_client.post(
            _row_save_url(event, integration),
            data={
                "index": "0",
                "question_0": "Suggested",
                "target_0": "track",
                "entoption_0": ["RPG", "LARP"],
                "entname_0": ["RPG sessions", "LARP"],
                "entslug_0": ["rpg", ""],
                "entcatchname_0": "Other",
                "entcatchslug_0": "",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_tab_url(event, integration),
            messages=[(messages.SUCCESS, "Question saved.")],
        )
        integration.refresh_from_db()
        target = ImportSettings.model_validate_json(
            integration.settings_json
        ).questions["Suggested"]
        assert target.to == "track"
        assert target.confirmed is True
        assert target.values == {
            "RPG": EntityRef(name="RPG sessions", slug="rpg"),
            "LARP": EntityRef(name="LARP", slug="larp"),
        }
        assert target.catchall == EntityRef(name="Other", slug="other")

    def test_post_saves_overrides_for_any_target(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        response = authenticated_client.post(
            _row_save_url(event, integration),
            data={
                "index": "0",
                "question_0": "Cap",
                "target_0": "session.participants_limit",
                "ovraw_0": ["maybe 8, maybe 10", "lots", ""],
                "ovreplacement_0": ["10", "20", "ignored-because-no-key"],
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_tab_url(event, integration),
            messages=[(messages.SUCCESS, "Question saved.")],
        )
        integration.refresh_from_db()
        target = ImportSettings.model_validate_json(
            integration.settings_json
        ).questions["Cap"]
        assert target.to == "session.participants_limit"
        assert target.overrides == {"maybe 8, maybe 10": "10", "lots": "20"}

    def test_post_preserves_other_questions_and_definitions(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        integration.settings_json = json.dumps(
            {
                "questions": {
                    "Already": {"to": "session.title", "confirmed": True},
                    "Other": {"ignore": True},
                },
                "definitions": {
                    "session_fields": {"existing": {"name": "Existing", "type": "text"}}
                },
            }
        )
        integration.save(update_fields=["settings_json"])

        response = authenticated_client.post(
            _row_save_url(event, integration),
            data={
                "index": "0",
                "question_0": "Fresh",
                "target_0": "session.description",
            },
        )

        assert response.status_code == HTTPStatus.FOUND
        integration.refresh_from_db()
        settings = ImportSettings.model_validate_json(integration.settings_json)
        # Per-row save preserves untouched questions and definitions.
        assert set(settings.questions) == {"Already", "Other", "Fresh"}
        assert settings.questions["Fresh"].to == "session.description"
        assert settings.questions["Fresh"].confirmed is True
        assert settings.questions["Already"].confirmed is True
        assert settings.definitions.session_fields["existing"].name == "Existing"

    def test_post_with_hx_request_returns_hx_redirect(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        response = authenticated_client.post(
            _row_save_url(event, integration),
            data={"index": "0", "question_0": "Title", "target_0": "session.title"},
            headers={"HX-Request": "true"},
        )

        assert response.status_code == HTTPStatus.NO_CONTENT
        assert response["HX-Redirect"] == _tab_url(event, integration)
        integration.refresh_from_db()
        target = ImportSettings.model_validate_json(
            integration.settings_json
        ).questions["Title"]
        assert target.confirmed is True

    def test_post_advances_to_next_question_when_more_remain(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        integration.questions_snapshot_json = json.dumps(
            [
                {"title": "Title", "field_type": "text"},
                {"title": "System", "field_type": "text"},
                {"title": "Notes", "field_type": "text"},
            ]
        )
        integration.save(update_fields=["questions_snapshot_json"])

        response = authenticated_client.post(
            _row_save_url(event, integration),
            data={"index": "0", "question_0": "Title", "target_0": "session.title"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_review_url(event, integration) + "?edit=1",
            messages=[(messages.SUCCESS, "Question saved.")],
        )

    def test_post_returns_to_summary_when_last_question_saved(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        integration.questions_snapshot_json = json.dumps(
            [
                {"title": "Title", "field_type": "text"},
                {"title": "Last", "field_type": "text"},
            ]
        )
        integration.save(update_fields=["questions_snapshot_json"])

        response = authenticated_client.post(
            _row_save_url(event, integration),
            data={"index": "1", "question_1": "Last", "target_1": "session.title"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_tab_url(event, integration),
            messages=[(messages.SUCCESS, "Question saved.")],
        )

    def test_post_with_invalid_index_redirects_with_error(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        before = integration.settings_json

        response = authenticated_client.post(
            _row_save_url(event, integration),
            data={"index": "abc", "target_0": "session.title"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_review_url(event, integration),
            messages=[(messages.ERROR, "Invalid row submission.")],
        )
        integration.refresh_from_db()
        assert integration.settings_json == before


@pytest.mark.django_db
class TestEventImportRefetchView:
    def _refetch_url(self, event, integration) -> str:
        return reverse(
            "panel:import-refetch", kwargs={"slug": event.slug, "pk": integration.pk}
        )

    def test_post_redirects_non_manager(
        self, authenticated_client, event, connection_with_secret
    ):
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        response = authenticated_client.post(self._refetch_url(event, integration))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_post_stores_snapshot_and_drops_confirmed(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        integration.settings_json = json.dumps(
            {
                "questions": {
                    "Title": {"to": "session.title", "confirmed": True},
                    "Gone": {"to": "session.description", "confirmed": True},
                },
                "definitions": {
                    "session_fields": {"existing": {"name": "Existing", "type": "text"}}
                },
            }
        )
        integration.save(update_fields=["settings_json"])

        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.return_value = MagicMock(
                ok=True,
                json=lambda: {
                    "items": [
                        {"title": "Title", "questionItem": {"question": {}}},
                        {"title": "Fresh", "questionItem": {"question": {}}},
                    ]
                },
            )
            response = authenticated_client.post(self._refetch_url(event, integration))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_run_page_url(event, integration),
            messages=[(messages.SUCCESS, "Form refetched: 2 questions.")],
        )
        integration.refresh_from_db()
        # Snapshot now matches the freshly fetched form.
        snapshot = json.loads(integration.questions_snapshot_json)
        assert [q["title"] for q in snapshot] == ["Title", "Fresh"]
        # Confirmed flag dropped on surviving entries; questions absent from
        # the new form are removed; definitions stay intact.
        settings = ImportSettings.model_validate_json(integration.settings_json)
        assert set(settings.questions) == {"Title"}
        assert settings.questions["Title"].confirmed is False
        assert settings.definitions.session_fields["existing"].name == "Existing"


@pytest.mark.django_db
class TestEventImportMissingFieldsView:
    def _url(self, event, integration) -> str:
        return reverse(
            "panel:import-missing-fields",
            kwargs={"slug": event.slug, "pk": integration.pk},
        )

    def test_post_redirects_non_manager(
        self, authenticated_client, event, connection_with_secret
    ):
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        response = authenticated_client.post(self._url(event, integration))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_post_adds_new_questions_and_keeps_existing_confirmations(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        integration.settings_json = json.dumps(
            {
                "questions": {
                    "Title": {"to": "session.title", "confirmed": True},
                    "Gone": {"to": "session.description", "confirmed": True},
                },
                "definitions": {
                    "session_fields": {"existing": {"name": "Existing", "type": "text"}}
                },
            }
        )
        integration.save(update_fields=["settings_json"])

        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.return_value = MagicMock(
                ok=True,
                json=lambda: {
                    "items": [
                        {"title": "Title", "questionItem": {"question": {}}},
                        {"title": "Fresh", "questionItem": {"question": {}}},
                    ]
                },
            )
            response = authenticated_client.post(self._url(event, integration))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_run_page_url(event, integration),
            messages=[(messages.SUCCESS, "Imported 1 new field(s).")],
        )
        integration.refresh_from_db()
        snapshot = json.loads(integration.questions_snapshot_json)
        assert [q["title"] for q in snapshot] == ["Title", "Fresh"]
        # Existing mappings and confirmations are preserved; "Gone" stays since
        # we don't drop questions that disappeared from the form.
        settings = ImportSettings.model_validate_json(integration.settings_json)
        assert set(settings.questions) == {"Title", "Gone"}
        assert settings.questions["Title"].confirmed is True
        assert settings.definitions.session_fields["existing"].name == "Existing"

    def test_post_no_new_fields_emits_info_message(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        integration.settings_json = json.dumps(
            {"questions": {"Title": {"to": "session.title", "confirmed": True}}}
        )
        integration.save(update_fields=["settings_json"])

        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.return_value = MagicMock(
                ok=True,
                json=lambda: {
                    "items": [{"title": "Title", "questionItem": {"question": {}}}]
                },
            )
            response = authenticated_client.post(self._url(event, integration))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_run_page_url(event, integration),
            messages=[
                (
                    messages.INFO,
                    "No new fields to import; every form question is already mapped.",
                )
            ],
        )


@pytest.mark.django_db
class TestEventImportRunActionView:
    def test_post_redirects_non_manager(self, authenticated_client, event, connection):
        integration = _make_import_integration(event, connection, display_name="Puller")

        response = authenticated_client.post(_run_url(event, integration))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_post_creates_one_proposal_per_response(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        integration.settings_json = json.dumps(
            {"questions": {"Title": {"to": "session.title", "ignore": False}}}
        )
        integration.save(update_fields=["settings_json"])

        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.side_effect = _sheets_get(
                [["Title"], ["My Talk"], ["Another"]]
            )
            response = authenticated_client.post(_run_url(event, integration))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_run_page_url(event, integration),
            messages=[(messages.SUCCESS, "Created 2 proposals.")],
        )
        titles = set(
            Session.objects.filter(sphere=sphere).values_list("title", flat=True)
        )
        assert titles == {"My Talk", "Another"}

    def test_post_provisions_a_new_field_and_fills_it(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        integration.settings_json = json.dumps(
            {
                "questions": {
                    "Title": {"to": "session.title", "ignore": False},
                    "RPG system": {"to": "field.system", "ignore": False},
                },
                "definitions": {
                    "session_fields": {"system": {"name": "System", "type": "text"}}
                },
            }
        )
        integration.save(update_fields=["settings_json"])

        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.side_effect = _sheets_get(
                [["Title", "RPG system"], ["My Talk", "D&D"]]
            )
            response = authenticated_client.post(_run_url(event, integration))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_run_page_url(event, integration),
            messages=[(messages.SUCCESS, "Created 1 proposals.")],
        )
        field = SessionField.objects.get(event=event, slug="system")
        assert field.name == "System"
        assert field.question == "RPG system"
        session = Session.objects.get(sphere=sphere, title="My Talk")
        value = SessionFieldValue.objects.get(session=session, field=field)
        assert value.value == "D&D"

    def test_post_provisions_a_session_field_with_its_definition(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        integration.settings_json = json.dumps(
            {
                "questions": {
                    "Title": {"to": "session.title", "ignore": False},
                    "System": {"to": "field.system", "ignore": False},
                },
                "definitions": {
                    "personal_fields": {},
                    "session_fields": {
                        "system": {
                            "name": "System",
                            "type": "select",
                            "multiple": True,
                            "allow_custom": True,
                            "options": ["D&D", "Warhammer"],
                        }
                    },
                },
            }
        )
        integration.save(update_fields=["settings_json"])

        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.side_effect = _sheets_get(
                [["Title", "System"], ["My Talk", "D&D"]]
            )
            response = authenticated_client.post(_run_url(event, integration))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_run_page_url(event, integration),
            messages=[(messages.SUCCESS, "Created 1 proposals.")],
        )
        field = SessionField.objects.get(event=event, slug="system")
        assert field.field_type == "select"
        assert field.is_multiple is True
        assert field.allow_custom is True
        assert list(
            SessionFieldOption.objects.filter(field=field)
            .order_by("order")
            .values_list("value", flat=True)
        ) == ["D&D", "Warhammer"]

    def test_post_provisions_a_personal_field_without_values(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        integration.settings_json = json.dumps(
            {
                "questions": {
                    "Title": {"to": "session.title", "ignore": False},
                    "Phone": {"to": "personal.telefon", "ignore": False},
                },
                "definitions": {
                    "personal_fields": {
                        "telefon": {
                            "name": "Telefon",
                            "type": "text",
                            "multiple": False,
                            "allow_custom": False,
                            "options": [],
                        }
                    },
                    "session_fields": {},
                },
            }
        )
        integration.save(update_fields=["settings_json"])

        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.side_effect = _sheets_get(
                [["Title", "Phone"], ["My Talk", "555-1234"]]
            )
            authenticated_client.post(_run_url(event, integration))
            # Re-run: the field is matched by slug, not duplicated.
            authenticated_client.post(_run_url(event, integration))

        fields = PersonalDataField.objects.filter(event=event, slug="telefon")
        assert fields.count() == 1
        assert fields.get().field_type == "text"
        assert not HostPersonalData.objects.filter(field=fields.get()).exists()

    def test_post_writes_personal_field_value_against_row_facilitator(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        integration.settings_json = json.dumps(
            {
                "questions": {
                    "Title": {"to": "session.title", "ignore": False},
                    "Nick": {"to": "facilitator.display_name", "ignore": False},
                    "Phone": {"to": "personal.telefon", "ignore": False},
                },
                "definitions": {
                    "personal_fields": {
                        "telefon": {
                            "name": "Telefon",
                            "type": "text",
                            "multiple": False,
                            "allow_custom": False,
                            "options": [],
                        }
                    },
                    "session_fields": {},
                },
            }
        )
        integration.save(update_fields=["settings_json"])

        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.side_effect = _sheets_get(
                [["Title", "Nick", "Phone"], ["My Talk", "GM Bob", "555-1234"]]
            )
            authenticated_client.post(_run_url(event, integration))
            # Re-run: HostPersonalData upserts on (facilitator, event, field) —
            # the row's value overwrites rather than duplicating.
            session_cls.return_value.get.side_effect = _sheets_get(
                [["Title", "Nick", "Phone"], ["My Talk", "GM Bob", "555-9999"]]
            )
            authenticated_client.post(_run_url(event, integration))

        field = PersonalDataField.objects.get(event=event, slug="telefon")
        rows = list(HostPersonalData.objects.filter(field=field))
        assert len(rows) == 1
        assert rows[0].value == "555-9999"
        assert rows[0].facilitator.display_name == "GM Bob"

    def test_post_provisions_and_attaches_time_slots(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        integration.settings_json = json.dumps(
            {
                "questions": {
                    "Title": {"to": "session.title", "ignore": False},
                    "When": {
                        "to": "session.time_slots",
                        "values": {
                            "Fri": {
                                "to": "time_slot",
                                "start_time": "2025-09-19T16:00:00+02:00",
                                "end_time": "2025-09-19T22:00:00+02:00",
                            }
                        },
                    },
                }
            }
        )
        integration.save(update_fields=["settings_json"])

        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.side_effect = _sheets_get(
                [["Title", "When"], ["My Talk", "Fri"]]
            )
            authenticated_client.post(_run_url(event, integration))

        session = Session.objects.get(sphere=sphere, title="My Talk")
        slots = list(session.time_slots.all())
        assert len(slots) == 1
        assert slots[0].start_time == datetime.fromisoformat(
            "2025-09-19T16:00:00+02:00"
        )
        assert slots[0].end_time == datetime.fromisoformat("2025-09-19T22:00:00+02:00")

    def test_post_provisions_and_attaches_tracks(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        integration.settings_json = json.dumps(
            {
                "questions": {
                    "Title": {"to": "session.title", "ignore": False},
                    "Suggested": {
                        "to": "track",
                        "values": {"RPG": {"name": "RPG sessions", "slug": "rpg"}},
                        "catchall": {"name": "Other", "slug": "other"},
                    },
                }
            }
        )
        integration.save(update_fields=["settings_json"])

        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.side_effect = _sheets_get(
                [["Title", "Suggested"], ["My Talk", "RPG"], ["Loose", "Custom"]]
            )
            authenticated_client.post(_run_url(event, integration))

        # The configured option provisions and attaches its track...
        rpg = Track.objects.get(event=event, slug="rpg")
        assert rpg.name == "RPG sessions"
        matched = Session.objects.get(sphere=sphere, title="My Talk")
        assert list(matched.tracks.all()) == [rpg]
        # ...and a custom answer lands in the catchall track.
        other = Track.objects.get(event=event, slug="other")
        loose = Session.objects.get(sphere=sphere, title="Loose")
        assert list(loose.tracks.all()) == [other]

    def test_post_provisions_and_sets_the_category(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        integration.settings_json = json.dumps(
            {
                "questions": {
                    "Title": {"to": "session.title", "ignore": False},
                    "Kind": {
                        "to": "category",
                        "values": {"RPG": {"name": "RPG session", "slug": "rpg"}},
                        "catchall": {"name": "Other", "slug": "other"},
                    },
                }
            }
        )
        integration.save(update_fields=["settings_json"])

        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.side_effect = _sheets_get(
                [["Title", "Kind"], ["My Talk", "RPG"], ["Loose", "Custom"]]
            )
            authenticated_client.post(_run_url(event, integration))

        # The configured option provisions and sets its category...
        rpg = ProposalCategory.objects.get(event=event, slug="rpg")
        assert rpg.name == "RPG session"
        matched = Session.objects.get(sphere=sphere, title="My Talk")
        assert matched.category_id == rpg.pk
        # ...and a custom answer lands in the catchall category.
        other = ProposalCategory.objects.get(event=event, slug="other")
        loose = Session.objects.get(sphere=sphere, title="Loose")
        assert loose.category_id == other.pk


@pytest.mark.django_db
class TestEventImportTestRowActionView:
    def test_post_redirects_non_manager(self, authenticated_client, event, connection):
        integration = _make_import_integration(event, connection, display_name="Puller")

        response = authenticated_client.post(_test_url(event, integration))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_post_imports_exactly_one_random_row(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        integration.settings_json = json.dumps(
            {"questions": {"Title": {"to": "session.title", "ignore": False}}}
        )
        integration.save(update_fields=["settings_json"])

        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.side_effect = _sheets_get(
                [["Title"], ["One"], ["Two"], ["Three"]]
            )
            response = authenticated_client.post(_test_url(event, integration))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_run_page_url(event, integration),
            messages=[
                (
                    messages.SUCCESS,
                    (
                        "Test import created one proposal from a random row. Review "
                        "it, then delete it before running the full import."
                    ),
                )
            ],
        )
        sessions = Session.objects.filter(sphere=sphere)
        assert sessions.count() == 1
        assert sessions.get().title in {"One", "Two", "Three"}

    def test_post_with_no_responses_reports_nothing_to_test(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.side_effect = _sheets_get([])
            response = authenticated_client.post(_test_url(event, integration))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_run_page_url(event, integration),
            messages=[(messages.INFO, "No responses found to test.")],
        )
        assert not Session.objects.filter(sphere=sphere).exists()


@pytest.mark.django_db
class TestEventImportJsonView:
    def test_get_redirects_non_manager(self, authenticated_client, event, connection):
        integration = _make_import_integration(event, connection, display_name="Puller")

        response = authenticated_client.get(_json_url(event, integration))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_get_prettifies_the_stored_settings(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        stored = json.dumps(
            {"questions": {"Title": {"to": "session.title", "ignore": False}}}
        )
        integration.settings_json = stored
        integration.save(update_fields=["settings_json"])

        response = authenticated_client.get(_json_url(event, integration))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/import-json.html",
            context_data=_event_context(event)
            | {
                "active_nav": "import",
                "active_integration": _dto(integration),
                "active_tab": "json",
                "tab_urls": import_tab_urls(event.slug, integration.pk),
                "settings_json": json.dumps(
                    json.loads(stored), indent=2, ensure_ascii=False
                ),
            },
        )

    def test_post_saves_valid_json(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        blob = '{"questions": {"Title": {"to": "session.title"}}}'

        response = authenticated_client.post(
            _json_url(event, integration), data={"settings_json": blob}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_json_url(event, integration),
            messages=[(messages.SUCCESS, "Import settings saved.")],
        )
        integration.refresh_from_db()
        assert integration.settings_json == blob

    def test_post_refreshes_snapshot_when_header_row_changes(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        integration.settings_json = json.dumps({"header_row": 1})
        integration.questions_snapshot_json = json.dumps([{"title": "Stale"}])
        integration.save(update_fields=["settings_json", "questions_snapshot_json"])

        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.return_value = MagicMock(
                ok=True,
                json=lambda: {
                    "items": [{"title": "Fresh", "questionItem": {"question": {}}}]
                },
            )
            response = authenticated_client.post(
                _json_url(event, integration),
                data={"settings_json": json.dumps({"header_row": 2})},
            )

        assert response.status_code == HTTPStatus.FOUND
        integration.refresh_from_db()
        snapshot = json.loads(integration.questions_snapshot_json)
        assert [q["title"] for q in snapshot] == ["Fresh"]

    def test_post_keeps_snapshot_when_parsing_fields_unchanged(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        integration.settings_json = json.dumps({"header_row": 1})
        integration.questions_snapshot_json = json.dumps([{"title": "Kept"}])
        integration.save(update_fields=["settings_json", "questions_snapshot_json"])

        response = authenticated_client.post(
            _json_url(event, integration),
            data={
                "settings_json": json.dumps(
                    {"header_row": 1, "questions": {"Title": {"to": "session.title"}}}
                )
            },
        )

        assert response.status_code == HTTPStatus.FOUND
        integration.refresh_from_db()
        snapshot = json.loads(integration.questions_snapshot_json)
        assert [q["title"] for q in snapshot] == ["Kept"]

    def test_post_rejects_invalid_json(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        before = integration.settings_json

        response = authenticated_client.post(
            _json_url(event, integration), data={"settings_json": "{not json"}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/import-json.html",
            messages=[(messages.ERROR, "Invalid import settings JSON.")],
            context_data=_event_context(event)
            | {
                "active_nav": "import",
                "active_integration": _dto(integration),
                "active_tab": "json",
                "tab_urls": import_tab_urls(event.slug, integration.pk),
                "settings_json": "{not json",
            },
        )
        integration.refresh_from_db()
        assert integration.settings_json == before


@pytest.mark.django_db
class TestEventImportRunPageView:
    def test_get_redirects_non_manager(self, authenticated_client, event, connection):
        integration = _make_import_integration(event, connection, display_name="Puller")

        response = authenticated_client.get(_run_page_url(event, integration))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_get_renders_the_run_actions(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        response = authenticated_client.get(_run_page_url(event, integration))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/import-run.html",
            context_data=_event_context(event)
            | {
                "active_nav": "import",
                "active_integration": _dto(integration),
                "active_tab": "run",
                "tab_urls": import_tab_urls(event.slug, integration.pk),
                "header_row": 1,
                "email_column": None,
                "unique_key_columns": [],
                "available_columns": ["Timestamp", "Email Address"],
                "fields_imported": False,
                "fields_count": 0,
                "mapping_total": 0,
                "mapping_confirmed": 0,
                "no_unique_keys_label": "No columns selected.",
            },
        )

    def test_get_reports_imported_fields_and_mapping_progress(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        integration.questions_snapshot_json = json.dumps(
            [
                {
                    "title": "Title",
                    "options": [],
                    "field_type": "text",
                    "is_multiple": False,
                    "allow_custom": False,
                },
                {
                    "title": "System",
                    "options": [],
                    "field_type": "text",
                    "is_multiple": False,
                    "allow_custom": False,
                },
            ]
        )
        header_row = 3
        integration.settings_json = json.dumps(
            {
                "header_row": header_row,
                "unique_key_columns": ["Email Address"],
                "questions": {
                    "Title": {"to": "session.title", "confirmed": True},
                    "System": {"to": "field.system"},
                },
            }
        )
        integration.save(update_fields=("questions_snapshot_json", "settings_json"))

        response = authenticated_client.get(_run_page_url(event, integration))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/import-run.html",
            context_data=_event_context(event)
            | {
                "active_nav": "import",
                "active_integration": _dto(integration),
                "active_tab": "run",
                "tab_urls": import_tab_urls(event.slug, integration.pk),
                "header_row": header_row,
                "email_column": None,
                "unique_key_columns": ["Email Address"],
                "available_columns": ["Timestamp", "Email Address", "Title", "System"],
                "fields_imported": True,
                "fields_count": len(["Title", "System"]),
                "mapping_total": len(["Title", "System"]),
                "mapping_confirmed": 1,
                "no_unique_keys_label": "No columns selected.",
            },
        )


@pytest.mark.django_db
class TestEventImportSettingsSaveView:
    def _save_url(self, event, integration) -> str:
        return reverse(
            "panel:import-settings-save",
            kwargs={"slug": event.slug, "pk": integration.pk},
        )

    def test_post_redirects_non_manager(self, authenticated_client, event, connection):
        integration = _make_import_integration(event, connection, display_name="Puller")

        response = authenticated_client.post(self._save_url(event, integration))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_post_saves_header_row_and_unique_keys_then_returns_to_run_tab(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        header_row = 3

        response = authenticated_client.post(
            self._save_url(event, integration),
            data={
                "header_row": str(header_row),
                "unique_key_columns": ["Title", " Email "],
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_run_page_url(event, integration),
            messages=[(messages.SUCCESS, "Sheet settings saved.")],
        )
        integration.refresh_from_db()
        settings = ImportSettings.model_validate_json(integration.settings_json)
        assert settings.header_row == header_row
        assert settings.unique_key_columns == ["Title", "Email"]

    def test_post_rejects_non_positive_header_row(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        response = authenticated_client.post(
            self._save_url(event, integration), data={"header_row": "0"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_run_page_url(event, integration),
            messages=[(messages.ERROR, "Header row must be 1 or greater.")],
        )

    def test_post_saves_email_column_when_provided(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        email_column = 2

        response = authenticated_client.post(
            self._save_url(event, integration),
            data={"header_row": "1", "email_column": str(email_column)},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_run_page_url(event, integration),
            messages=[(messages.SUCCESS, "Sheet settings saved.")],
        )
        integration.refresh_from_db()
        settings = ImportSettings.model_validate_json(integration.settings_json)
        assert settings.email_column == email_column

    def test_post_clears_email_column_when_blank(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        integration.settings_json = json.dumps({"email_column": 2})
        integration.save(update_fields=["settings_json"])

        response = authenticated_client.post(
            self._save_url(event, integration),
            data={"header_row": "1", "email_column": ""},
        )

        assert response.status_code == HTTPStatus.FOUND
        integration.refresh_from_db()
        settings = ImportSettings.model_validate_json(integration.settings_json)
        assert settings.email_column is None

    def test_post_rejects_non_positive_email_column(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        response = authenticated_client.post(
            self._save_url(event, integration),
            data={"header_row": "1", "email_column": "0"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_run_page_url(event, integration),
            messages=[(messages.ERROR, "Email column must be 1 or greater.")],
        )


@pytest.mark.django_db
class TestEventImportLogPageView:
    def test_get_redirects_non_manager(
        self, authenticated_client, event, connection_with_secret
    ):
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        response = authenticated_client.get(_log_url(event, integration))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_get_renders_empty_state_without_attempts(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        response = authenticated_client.get(_log_url(event, integration))

        assert response.status_code == HTTPStatus.OK
        assert response.context_data["log_total_attempts"] == 0

    def test_get_groups_errors_and_successes_and_folds_successes_by_default(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        integration.settings_json = json.dumps(
            {"questions": {"Title": {"to": "session.title"}}}
        )
        integration.save(update_fields=["settings_json"])

        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.side_effect = _sheets_get(
                [["Title"], ["My Talk"]]
            )
            authenticated_client.post(_run_url(event, integration))

        response = authenticated_client.get(_log_url(event, integration))

        assert response.status_code == HTTPStatus.OK
        assert response.context_data["log_total_attempts"] == 1
        assert response.context_data["log_success_count"] == 1
        assert response.context_data["log_error_count"] == 0
        body = response.content.decode()
        # Successes are collapsed inside a <details> without `open`.
        assert "<details" in body
        assert "open" not in body.split("</details>")[0]

    def test_post_retry_creates_a_fresh_entry_and_redirects_to_log(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        integration.settings_json = json.dumps(
            {
                "questions": {
                    "Title": {"to": "session.title"},
                    "Cap": {"to": "session.participants_limit"},
                }
            }
        )
        integration.save(update_fields=["settings_json"])

        # First run yields one skipped entry.
        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.side_effect = _sheets_get(
                [["Title", "Cap"], ["Talk", "loads"]]
            )
            authenticated_client.post(_run_url(event, integration))

        entry = ImportLogEntry.objects.get(integration=integration)
        # Operator fixes the recipe, then retries.
        integration.settings_json = json.dumps(
            {"questions": {"Title": {"to": "session.title"}}}
        )
        integration.save(update_fields=["settings_json"])

        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.side_effect = _sheets_get(
                [["Title", "Cap"], ["Talk", "loads"]]
            )
            response = authenticated_client.post(
                _log_retry_url(event, integration), data={"entry_id": str(entry.pk)}
            )

        assert response.status_code == HTTPStatus.FOUND
        assert response.url == _log_url(event, integration)
        # The same log entry was upserted in place — same pk, now success.
        rows = list(ImportLogEntry.objects.filter(integration=integration))
        assert len(rows) == 1
        assert rows[0].pk == entry.pk
        assert rows[0].status == "success"
        assert rows[0].session_id is not None

    def test_post_retry_with_invalid_entry_id_redirects_with_error(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        response = authenticated_client.post(
            _log_retry_url(event, integration), data={"entry_id": "abc"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_log_url(event, integration),
            messages=[(messages.ERROR, "Invalid log entry.")],
        )

    def test_post_retry_with_foreign_entry_id_refuses_and_writes_nothing(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        # Object-scope auth: an entry belonging to another event must not be
        # actionable through this event's retry endpoint.
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        other_event = EventFactory(sphere=sphere)
        other_integration = _make_import_integration(
            other_event, connection_with_secret, display_name="Other Puller"
        )
        foreign = ImportLogEntry.objects.create(
            integration=other_integration,
            row_index=0,
            status="skipped",
            reason="seed",
            response_json="{}",
        )
        before = ImportLogEntry.objects.count()

        response = authenticated_client.post(
            _log_retry_url(event, integration), data={"entry_id": str(foreign.pk)}
        )

        assert response.status_code == HTTPStatus.FOUND
        assert ImportLogEntry.objects.count() == before


@pytest.mark.django_db
class TestEventImportLogFilters:
    def _seed(self, integration, *, sphere):
        # One success + one skipped entry, both with distinct titles for search.
        session = Session.objects.create(
            sphere=sphere,
            title="Dragons of Despair",
            slug="dragons-success",
            status="pending",
            participants_limit=0,
        )
        ImportLogEntry.objects.create(
            integration=integration,
            row_index=0,
            status="success",
            reason="",
            response_json="{}",
            title="Dragons of Despair",
            display_name="GM A",
            session=session,
        )
        ImportLogEntry.objects.create(
            integration=integration,
            row_index=1,
            status="skipped",
            reason="bad",
            response_json="{}",
            title="Wargames",
            display_name="GM B",
        )

    def test_status_pill_skipped_hides_successes(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        self._seed(integration, sphere=sphere)

        response = authenticated_client.get(
            _log_url(event, integration) + "?status=skipped"
        )

        assert response.status_code == HTTPStatus.OK
        assert response.context_data["log_status"] == "skipped"
        assert response.context_data["log_show_successes"] is False
        assert response.context_data["log_show_errors"] is True
        assert response.context_data["log_successes"] == []
        assert [e.title for e in response.context_data["log_errors"]] == ["Wargames"]

    def test_status_pill_success_hides_errors_and_opens_details(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        self._seed(integration, sphere=sphere)

        response = authenticated_client.get(
            _log_url(event, integration) + "?status=success"
        )

        assert response.status_code == HTTPStatus.OK
        assert response.context_data["log_show_errors"] is False
        assert response.context_data["log_successes_open"] is True
        assert response.context_data["log_errors"] == []
        assert [e.title for e in response.context_data["log_successes"]] == [
            "Dragons of Despair"
        ]
        # The success <details> renders with the open attribute.
        body = response.content.decode()
        assert "<details" in body
        assert "open" in body.split("</details>")[0]

    def test_search_narrows_to_matching_title_or_display_name(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        self._seed(integration, sphere=sphere)

        response = authenticated_client.get(
            _log_url(event, integration) + "?search=dragon"
        )

        assert response.status_code == HTTPStatus.OK
        assert response.context_data["log_search"] == "dragon"
        assert [e.title for e in response.context_data["log_successes"]] == [
            "Dragons of Despair"
        ]
        assert response.context_data["log_errors"] == []

    def test_status_pill_urls_url_encode_the_search_term(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        self._seed(integration, sphere=sphere)

        response = authenticated_client.get(
            _log_url(event, integration) + "?search=A%26B%3Dc"
        )

        assert response.status_code == HTTPStatus.OK
        assert response.context_data["log_search"] == "A&B=c"
        all_url = response.context_data["log_filter_urls"]["all"]
        assert "search=A%26B%3Dc" in all_url
        assert "&search=A&B=c" not in all_url

    def test_search_and_status_combine(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        self._seed(integration, sphere=sphere)

        response = authenticated_client.get(
            _log_url(event, integration) + "?status=skipped&search=wargames"
        )

        assert response.status_code == HTTPStatus.OK
        assert [e.title for e in response.context_data["log_errors"]] == ["Wargames"]
        assert response.context_data["log_successes"] == []

    def test_invalid_status_falls_back_to_all(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        self._seed(integration, sphere=sphere)

        response = authenticated_client.get(
            _log_url(event, integration) + "?status=bogus"
        )

        assert response.status_code == HTTPStatus.OK
        assert response.context_data["log_status"] == "all"


@pytest.mark.django_db
class TestEventImportLogReimport:
    def _setup(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        integration.settings_json = json.dumps(
            {"questions": {"Title": {"to": "session.title"}}}
        )
        integration.save(update_fields=["settings_json"])

        # Initial run creates one proposal + one success log entry.
        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.side_effect = _sheets_get(
                [["Title"], ["Original"]]
            )
            authenticated_client.post(_run_url(event, integration))

        entry = ImportLogEntry.objects.get(integration=integration, status="success")
        return integration, entry

    def test_post_overwrites_session_with_source_row_and_writes_log_entry(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        integration, entry = self._setup(
            authenticated_client, active_user, sphere, event, connection_with_secret
        )
        session_pk = entry.session_id
        # Operator edits the proposal in the panel.
        Session.objects.filter(pk=session_pk).update(title="Hand-edited")

        # Reimport: refetched source still returns the original title.
        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.side_effect = _sheets_get(
                [["Title"], ["Original"]]
            )
            response = authenticated_client.post(
                _log_reimport_url(event, integration), data={"entry_id": str(entry.pk)}
            )

        assert response.status_code == HTTPStatus.FOUND
        assert response.url == _log_url(event, integration)
        # Title is back to the source value; session pk is unchanged.
        Session.objects.get(pk=session_pk).refresh_from_db()
        assert Session.objects.get(pk=session_pk).title == "Original"
        # The same log entry is updated in place — same pk, same session FK.
        entries = list(ImportLogEntry.objects.filter(integration=integration))
        assert len(entries) == 1
        assert entries[0].pk == entry.pk
        assert entries[0].status == "success"
        assert entries[0].session_id == session_pk

    def test_template_renders_reimport_confirm_dialog(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        integration, _entry = self._setup(
            authenticated_client, active_user, sphere, event, connection_with_secret
        )

        response = authenticated_client.get(
            _log_url(event, integration) + "?status=success"
        )

        body = response.content.decode()
        assert "onsubmit=" in body
        assert "Reimport will overwrite" in body
        assert _log_reimport_url(event, integration) in body

    def test_post_clears_contact_email_when_source_row_blanks_it(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        integration.settings_json = json.dumps(
            {
                "questions": {
                    "Title": {"to": "session.title"},
                    "Email": {"to": "session.contact_email"},
                }
            }
        )
        integration.save(update_fields=["settings_json"])

        # Initial run imports a contact email.
        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.side_effect = _sheets_get(
                [["Title", "Email"], ["Original", "host@example.com"]]
            )
            authenticated_client.post(_run_url(event, integration))

        entry = ImportLogEntry.objects.get(integration=integration, status="success")
        assert Session.objects.get(pk=entry.session_id).contact_email == (
            "host@example.com"
        )

        # Reimport: the source row no longer carries an email.
        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.side_effect = _sheets_get(
                [["Title", "Email"], ["Original", ""]]
            )
            authenticated_client.post(
                _log_reimport_url(event, integration), data={"entry_id": str(entry.pk)}
            )

        reimported = Session.objects.get(pk=entry.session_id)
        assert not reimported.contact_email


def _apply_field_layout_url(event, integration) -> str:
    return reverse(
        "panel:import-apply-field-layout",
        kwargs={"slug": event.slug, "pk": integration.pk},
    )


@pytest.mark.django_db
class TestEventImportApplyFieldLayoutView:
    def test_post_redirects_non_manager(
        self, authenticated_client, event, connection_with_secret
    ):
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        response = authenticated_client.post(
            _apply_field_layout_url(event, integration)
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_post_adds_new_field_values_drops_removed_and_prunes_orphans(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        # Initial state: a session imported earlier with two session fields
        # ("system", "genre"). Operator has since changed the recipe — only
        # "genre" remains mapped, and "audience" is freshly mapped. Apply
        # field layout should: add an audience value from the cached row,
        # drop the system value, leave the genre value alone, and prune the
        # now-orphan "system" SessionField.
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        session = Session.objects.create(
            category=category,
            display_name="Host",
            title="Talk",
            slug="talk",
            sphere=sphere,
            participants_limit=4,
            status="pending",
        )
        old_system = SessionField.objects.create(
            event=event, name="System", question="System?", slug="system"
        )
        kept_genre = SessionField.objects.create(
            event=event, name="Genre", question="Genre?", slug="genre"
        )
        SessionFieldValue.objects.create(session=session, field=old_system, value="D&D")
        SessionFieldValue.objects.create(
            session=session, field=kept_genre, value="Fantasy"
        )
        ImportLogEntry.objects.create(
            integration=integration,
            row_index=0,
            status="success",
            response_json=json.dumps(
                {"Genre": "Fantasy", "Audience": "Adults"}, ensure_ascii=False
            ),
            title="Talk",
            session=session,
        )
        integration.settings_json = json.dumps(
            {
                "questions": {
                    "Genre": {"to": "field.genre"},
                    "Audience": {"to": "field.audience"},
                },
                "definitions": {
                    "session_fields": {
                        "genre": {"name": "Genre", "type": "text"},
                        "audience": {"name": "Audience", "type": "text"},
                    }
                },
            }
        )
        integration.save(update_fields=["settings_json"])

        response = authenticated_client.post(
            _apply_field_layout_url(event, integration)
        )

        assert response.status_code == HTTPStatus.FOUND
        # Retained mapping kept its existing value untouched.
        assert (
            SessionFieldValue.objects.get(session=session, field=kept_genre).value
            == "Fantasy"
        )
        # Newly mapped field provisioned + value added from the cached row.
        audience = SessionField.objects.get(event=event, slug="audience")
        assert (
            SessionFieldValue.objects.get(session=session, field=audience).value
            == "Adults"
        )
        # Value for the unmapped field dropped.
        assert not SessionFieldValue.objects.filter(
            session=session, field=old_system
        ).exists()
        # Orphan SessionField pruned.
        assert not SessionField.objects.filter(event=event, slug="system").exists()

    def test_post_fills_missing_contact_email_from_cached_row(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        # A session imported before the operator mapped session.contact_email.
        # The cached row carries the email; the recipe now maps it. Apply
        # field layout should fill the empty contact_email without touching
        # other built-in fields.
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        session = Session.objects.create(
            category=category,
            display_name="Host",
            title="Talk",
            slug="talk",
            sphere=sphere,
            participants_limit=4,
            status="pending",
        )
        ImportLogEntry.objects.create(
            integration=integration,
            row_index=0,
            status="success",
            response_json=json.dumps(
                {"Email": "anna@example.com", "Title": "Talk"}, ensure_ascii=False
            ),
            title="Talk",
            session=session,
        )
        integration.settings_json = json.dumps(
            {
                "questions": {
                    "Title": {"to": "session.title"},
                    "Email": {"to": "session.contact_email"},
                }
            }
        )
        integration.save(update_fields=["settings_json"])

        response = authenticated_client.post(
            _apply_field_layout_url(event, integration)
        )

        assert response.status_code == HTTPStatus.FOUND
        session.refresh_from_db()
        assert session.contact_email == "anna@example.com"
        # Title stays untouched.
        assert session.title == "Talk"

    def test_post_does_not_overwrite_existing_contact_email(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        session = Session.objects.create(
            category=category,
            display_name="Host",
            title="Talk",
            slug="talk",
            sphere=sphere,
            participants_limit=4,
            status="pending",
            contact_email="existing@example.com",
        )
        ImportLogEntry.objects.create(
            integration=integration,
            row_index=0,
            status="success",
            response_json=json.dumps({"Email": "new@example.com"}, ensure_ascii=False),
            title="Talk",
            session=session,
        )
        integration.settings_json = json.dumps(
            {"questions": {"Email": {"to": "session.contact_email"}}}
        )
        integration.save(update_fields=["settings_json"])

        authenticated_client.post(_apply_field_layout_url(event, integration))

        session.refresh_from_db()
        assert session.contact_email == "existing@example.com"

    def test_post_adds_facilitator_when_session_has_none(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        session = Session.objects.create(
            category=category,
            display_name="Host",
            title="Talk",
            slug="talk",
            sphere=sphere,
            participants_limit=4,
            status="pending",
        )
        ImportLogEntry.objects.create(
            integration=integration,
            row_index=0,
            status="success",
            response_json=json.dumps({"Nick": "GM Bob"}, ensure_ascii=False),
            title="Talk",
            session=session,
        )
        integration.settings_json = json.dumps(
            {"questions": {"Nick": {"to": "facilitator.display_name"}}}
        )
        integration.save(update_fields=["settings_json"])

        authenticated_client.post(_apply_field_layout_url(event, integration))

        facilitators = list(session.facilitators.all())
        assert [f.display_name for f in facilitators] == ["GM Bob"]

    def test_post_does_not_replace_existing_facilitator(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        existing = Facilitator.objects.create(
            event=event, display_name="Existing Host", slug="existing-host"
        )
        session = Session.objects.create(
            category=category,
            display_name="Host",
            title="Talk",
            slug="talk",
            sphere=sphere,
            participants_limit=4,
            status="pending",
        )
        session.facilitators.add(existing)
        ImportLogEntry.objects.create(
            integration=integration,
            row_index=0,
            status="success",
            response_json=json.dumps({"Nick": "GM Bob"}, ensure_ascii=False),
            title="Talk",
            session=session,
        )
        integration.settings_json = json.dumps(
            {"questions": {"Nick": {"to": "facilitator.display_name"}}}
        )
        integration.save(update_fields=["settings_json"])

        authenticated_client.post(_apply_field_layout_url(event, integration))

        assert [f.pk for f in session.facilitators.all()] == [existing.pk]

    def test_post_sets_category_when_session_has_none(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        session = Session.objects.create(
            category=None,
            display_name="Host",
            title="Talk",
            slug="talk",
            sphere=sphere,
            participants_limit=4,
            status="pending",
        )
        ImportLogEntry.objects.create(
            integration=integration,
            row_index=0,
            status="success",
            response_json=json.dumps({"Kind": "RPG"}, ensure_ascii=False),
            title="Talk",
            session=session,
        )
        integration.settings_json = json.dumps(
            {
                "questions": {
                    "Kind": {
                        "to": "category",
                        "values": {
                            "RPG": EntityRef(name="RPG", slug="rpg").model_dump()
                        },
                    }
                }
            }
        )
        integration.save(update_fields=["settings_json"])

        authenticated_client.post(_apply_field_layout_url(event, integration))

        session.refresh_from_db()
        assert session.category is not None
        assert session.category.slug == "rpg"

    def test_post_adds_preferred_time_slots_when_session_has_none(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        session = Session.objects.create(
            category=category,
            display_name="Host",
            title="Talk",
            slug="talk",
            sphere=sphere,
            participants_limit=4,
            status="pending",
        )
        ImportLogEntry.objects.create(
            integration=integration,
            row_index=0,
            status="success",
            response_json=json.dumps({"Slots": "Saturday"}, ensure_ascii=False),
            title="Talk",
            session=session,
        )
        slot_spec = TimeSlotSpec(
            start_time=datetime(2026, 6, 19, 18, 0, tzinfo=UTC),
            end_time=datetime(2026, 6, 19, 22, 0, tzinfo=UTC),
        )
        integration.settings_json = json.dumps(
            {
                "questions": {
                    "Slots": {
                        "to": "session.time_slots",
                        "values": {"Saturday": slot_spec.model_dump(mode="json")},
                    }
                }
            }
        )
        integration.save(update_fields=["settings_json"])

        authenticated_client.post(_apply_field_layout_url(event, integration))

        time_slots = list(session.time_slots.all())
        assert len(time_slots) == 1
        # The slot was provisioned on the event.
        assert TimeSlot.objects.filter(event=event).count() == 1

    def test_post_adds_tracks_when_session_has_none(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        session = Session.objects.create(
            category=category,
            display_name="Host",
            title="Talk",
            slug="talk",
            sphere=sphere,
            participants_limit=4,
            status="pending",
        )
        ImportLogEntry.objects.create(
            integration=integration,
            row_index=0,
            status="success",
            response_json=json.dumps({"Track": "Indie"}, ensure_ascii=False),
            title="Talk",
            session=session,
        )
        integration.settings_json = json.dumps(
            {
                "questions": {
                    "Track": {
                        "to": "track",
                        "values": {
                            "Indie": EntityRef(name="Indie", slug="indie").model_dump()
                        },
                    }
                }
            }
        )
        integration.save(update_fields=["settings_json"])

        authenticated_client.post(_apply_field_layout_url(event, integration))

        tracks = list(session.tracks.all())
        assert [t.slug for t in tracks] == ["indie"]
        # The track was provisioned on the event.
        assert Track.objects.filter(event=event, slug="indie").exists()


# A cached snapshot serves the Proposal / Review tabs without touching the
# Google Forms API, so these label / row tests need no Google mocking.
def _cache_snapshot(integration, titles) -> None:
    integration.questions_snapshot_json = json.dumps(
        [{"title": t, "field_type": "text"} for t in titles]
    )
    integration.save(update_fields=["questions_snapshot_json"])


@pytest.mark.django_db
class TestImportSummaryLabels:
    def test_summary_covers_every_mapping_and_detail_branch(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        _cache_snapshot(
            integration, ["Dur", "Slots", "Fac", "Weird", "SF", "PF", "CB", "Ghost"]
        )
        integration.settings_json = json.dumps(
            {
                "questions": {
                    "Dur": {
                        "to": "session.duration",
                        "values": {"30 min": {"to": "duration", "iso": "PT30M"}},
                    },
                    "Slots": {
                        "to": "session.time_slots",
                        "values": {
                            "Fri": {
                                "to": "time_slot",
                                "start_time": "2025-09-19T16:00:00+02:00",
                                "end_time": "2025-09-19T22:00:00+02:00",
                            }
                        },
                    },
                    "Fac": {"to": "facilitator.bio"},
                    "Weird": {"to": "custom.x"},
                    "SF": {"to": "field.system"},
                    "PF": {"to": "personal.phone"},
                    "CB": {"to": "field.flag"},
                    "Ghost": {"to": "personal.ghost"},
                },
                "definitions": {
                    "personal_fields": {"phone": {"name": "Phone", "type": "text"}},
                    "session_fields": {
                        "system": {
                            "name": "System",
                            "type": "select",
                            "options": ["a", "b"],
                        },
                        "flag": {"name": "", "type": "checkbox"},
                    },
                },
            }
        )
        integration.save(update_fields=["settings_json"])

        response = authenticated_client.get(_tab_url(event, integration))

        assert response.status_code == HTTPStatus.OK
        assert response.context_data["summary_rows"] == [
            {
                "index": 0,
                "status": "unconfirmed",
                "question": "Dur",
                "mapping": "Proposal — Duration",
                "details": "1 mappings",
            },
            {
                "index": 1,
                "status": "unconfirmed",
                "question": "Slots",
                "mapping": "Time slots",
                "details": "1 windows",
            },
            {
                "index": 2,
                "status": "unconfirmed",
                "question": "Fac",
                "mapping": "Facilitator — Bio",
                "details": "",
            },
            {
                "index": 3,
                "status": "unconfirmed",
                "question": "Weird",
                "mapping": "",
                "details": "",
            },
            {
                "index": 4,
                "status": "unconfirmed",
                "question": "SF",
                "mapping": "Session field — System",
                "details": "Select — 2 options",
            },
            {
                "index": 5,
                "status": "unconfirmed",
                "question": "PF",
                "mapping": "Personal field — Phone",
                "details": "Text",
            },
            {
                "index": 6,
                "status": "unconfirmed",
                "question": "CB",
                "mapping": "Session field — flag",
                "details": "Checkbox",
            },
            {
                "index": 7,
                "status": "unconfirmed",
                "question": "Ghost",
                "mapping": "Personal field — ghost",
                "details": "",
            },
        ]


@pytest.mark.django_db
class TestImportReviewRowBranches:
    def test_rows_cover_personal_session_field_and_ignore_branches(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        _cache_snapshot(integration, ["PF", "PFnodef", "SF", "Ign"])
        integration.settings_json = json.dumps(
            {
                "questions": {
                    "PF": {"to": "personal.phone"},
                    "PFnodef": {"to": "personal.ghost"},
                    "SF": {"to": "field.system"},
                    "Ign": {"ignore": True},
                },
                "definitions": {
                    "personal_fields": {"phone": {"name": "Phone", "type": "text"}},
                    "session_fields": {
                        "system": {
                            "name": "System",
                            "type": "select",
                            "multiple": True,
                            "allow_custom": True,
                            "options": ["a", "b"],
                        }
                    },
                },
            }
        )
        integration.save(update_fields=["settings_json"])

        response = authenticated_client.get(_review_url(event, integration))

        assert response.status_code == HTTPStatus.OK
        rows = response.context_data["rows"]
        # Personal field with a saved definition: setup + name come from it.
        assert (rows[0]["selected"], rows[0]["field_slug"]) == (
            "personal-field",
            "phone",
        )
        assert rows[0]["field_name"] == "Phone"
        assert (rows[0]["field_type"], rows[0]["is_multiple"]) == ("text", False)
        # Personal field without a definition: mirror the source question, slug
        # falls back to the target slug for the name.
        assert (rows[1]["selected"], rows[1]["field_slug"]) == (
            "personal-field",
            "ghost",
        )
        assert rows[1]["field_name"] == "ghost"
        # Session field with a definition: type/multiple/options come from it.
        assert (rows[2]["selected"], rows[2]["field_slug"]) == (
            "session-field",
            "system",
        )
        assert rows[2]["field_name"] == "System"
        assert (rows[2]["field_type"], rows[2]["is_multiple"]) == ("select", True)
        assert rows[2]["allow_custom"] is True
        assert rows[2]["options"] == "a\nb"
        # An ignore target lands on the "ignore" selection.
        assert rows[3]["selected"] == "ignore"
        assert (rows[3]["field_name"], rows[3]["field_slug"]) == ("", "")


@pytest.mark.django_db
class TestImportRowSavePostHelpers:
    def test_post_saves_checkbox_session_field(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        response = authenticated_client.post(
            _row_save_url(event, integration),
            data={
                "index": "0",
                "question_0": "Online",
                "target_0": "session-field",
                "newname_0": "Online",
                "fieldtype_0": "checkbox",
            },
        )

        assert response.status_code == HTTPStatus.FOUND
        integration.refresh_from_db()
        definition = ImportSettings.model_validate_json(
            integration.settings_json
        ).definitions.session_fields["online"]
        assert definition.type == "checkbox"

    def test_post_saves_personal_field_defaulting_to_text(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        response = authenticated_client.post(
            _row_save_url(event, integration),
            data={
                "index": "0",
                "question_0": "Phone",
                "target_0": "personal-field",
                "newname_0": "Phone",
                "newslug_0": "phone",
                "fieldtype_0": "weird-value",
            },
        )

        assert response.status_code == HTTPStatus.FOUND
        integration.refresh_from_db()
        settings = ImportSettings.model_validate_json(integration.settings_json)
        assert settings.questions["Phone"].to == "personal.phone"
        # An unrecognised field type falls back to text.
        assert settings.definitions.personal_fields["phone"].type == "text"

    def test_post_saves_duration_target_and_skips_blank_iso(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        response = authenticated_client.post(
            _row_save_url(event, integration),
            data={
                "index": "0",
                "question_0": "Length",
                "target_0": "session.duration",
                "droption_0": ["30 min", "blank"],
                "driso_0": ["PT30M", "  "],
            },
        )

        assert response.status_code == HTTPStatus.FOUND
        integration.refresh_from_db()
        target = ImportSettings.model_validate_json(
            integration.settings_json
        ).questions["Length"]
        assert target.to == "session.duration"
        # The blank-ISO option is dropped; only the mapped one survives.
        assert set(target.values) == {"30 min"}

    def test_post_skips_blank_time_slot_row(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        response = authenticated_client.post(
            _row_save_url(event, integration),
            data={
                "index": "0",
                "question_0": "When",
                "target_0": "session.time_slots",
                "tsoption_0": ["Fri", ""],
                "tsstart_0": ["2025-09-19T16:00", ""],
                "tsend_0": ["2025-09-19T22:00", ""],
            },
        )

        assert response.status_code == HTTPStatus.FOUND
        integration.refresh_from_db()
        target = ImportSettings.model_validate_json(
            integration.settings_json
        ).questions["When"]
        # The trailing blank window row is ignored.
        assert set(target.values) == {"Fri"}

    def test_post_skips_entity_row_with_blank_name(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        response = authenticated_client.post(
            _row_save_url(event, integration),
            data={
                "index": "0",
                "question_0": "Suggested",
                "target_0": "category",
                "entoption_0": ["RPG", "Blank"],
                "entname_0": ["RPG", ""],
                "entslug_0": ["rpg", ""],
            },
        )

        assert response.status_code == HTTPStatus.FOUND
        integration.refresh_from_db()
        target = ImportSettings.model_validate_json(
            integration.settings_json
        ).questions["Suggested"]
        # The blank-name option is dropped.
        assert target.values == {"RPG": EntityRef(name="RPG", slug="rpg")}

    def test_post_ignores_when_field_target_has_no_slug(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        response = authenticated_client.post(
            _row_save_url(event, integration),
            data={
                "index": "0",
                "question_0": "Nope",
                "target_0": "session-field",
                "newname_0": "",
                "newslug_0": "",
            },
        )

        assert response.status_code == HTTPStatus.FOUND
        integration.refresh_from_db()
        target = ImportSettings.model_validate_json(
            integration.settings_json
        ).questions["Nope"]
        # A field target without a slug falls through to a deliberate ignore.
        assert target.to is None
        assert target.ignore is True


@pytest.mark.django_db
class TestImportJsonInvalidStored:
    def test_get_returns_raw_text_when_stored_json_is_invalid(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        integration.settings_json = "{not valid json"
        integration.save(update_fields=["settings_json"])

        response = authenticated_client.get(_json_url(event, integration))

        assert response.status_code == HTTPStatus.OK
        # Un-parseable stored settings are echoed back verbatim for the operator.
        assert response.context_data["settings_json"] == "{not valid json"


@pytest.mark.django_db
class TestImportActionResultMessages:
    def test_run_reports_responses_already_imported(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        integration.settings_json = json.dumps(
            {
                "questions": {"Title": {"to": "session.title"}},
                "unique_key_columns": ["Title"],
            }
        )
        integration.save(update_fields=["settings_json"])

        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.side_effect = _sheets_get(
                [["Title"], ["My Talk"], ["Another"]]
            )
            # follow=True so the first run's success message is consumed.
            authenticated_client.post(_run_url(event, integration), follow=True)

        # Second run finds both rows already imported via the unique key.
        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.side_effect = _sheets_get(
                [["Title"], ["My Talk"], ["Another"]]
            )
            response = authenticated_client.post(_run_url(event, integration))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_run_page_url(event, integration),
            messages=[
                (messages.SUCCESS, "Created 0 proposals."),
                (messages.INFO, "Skipped 2 responses already imported."),
            ],
        )

    def test_test_row_reports_skip_for_invalid_answer(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        integration.settings_json = json.dumps(
            {
                "questions": {
                    "Title": {"to": "session.title"},
                    "Cap": {"to": "session.participants_limit"},
                }
            }
        )
        integration.save(update_fields=["settings_json"])

        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.side_effect = _sheets_get(
                [["Title", "Cap"], ["My Talk", "loads"]]
            )
            response = authenticated_client.post(_test_url(event, integration))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_run_page_url(event, integration),
            messages=[
                (
                    messages.WARNING,
                    (
                        "Test row was skipped because one of its mapped answers "
                        "is invalid or has no mapping."
                    ),
                )
            ],
        )
        assert not Session.objects.filter(sphere=sphere).exists()

    def test_reimport_warns_when_source_row_is_gone(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )
        integration.settings_json = json.dumps(
            {"questions": {"Title": {"to": "session.title"}}}
        )
        integration.save(update_fields=["settings_json"])

        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.side_effect = _sheets_get(
                [["Title"], ["Original"]]
            )
            # follow=True so the initial run's success message is consumed.
            authenticated_client.post(_run_url(event, integration), follow=True)

        entry = ImportLogEntry.objects.get(integration=integration, status="success")

        # Reimport against a source that no longer carries the row.
        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value.get.side_effect = _sheets_get([])
            response = authenticated_client.post(
                _log_reimport_url(event, integration), data={"entry_id": str(entry.pk)}
            )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_log_url(event, integration),
            messages=[(messages.WARNING, "Reimport failed.")],
        )


_EVENT_NOT_FOUND_GET = (
    "panel:import-review",
    "panel:import-json",
    "panel:import-run",
    "panel:import-log",
)
_EVENT_NOT_FOUND_POST = (
    "panel:import-row-save",
    "panel:import-json",
    "panel:import-settings-save",
    "panel:import-run-do",
    "panel:import-test-do",
    "panel:import-log-retry",
    "panel:import-log-reimport",
    "panel:import-refetch",
    "panel:import-missing-fields",
    "panel:import-apply-field-layout",
)


@pytest.mark.django_db
class TestImportViewsEventNotFound:
    @pytest.mark.parametrize("name", _EVENT_NOT_FOUND_GET)
    def test_get_tabs_redirect_to_index_for_unknown_event(
        self, authenticated_client, active_user, sphere, name
    ):
        sphere.managers.add(active_user)
        url = reverse(name, kwargs={"slug": "no-such-event", "pk": 1})

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("panel:index"),
            messages=[(messages.ERROR, "Event not found.")],
        )

    @pytest.mark.parametrize("name", _EVENT_NOT_FOUND_POST)
    def test_post_actions_redirect_to_index_for_unknown_event(
        self, authenticated_client, active_user, sphere, name
    ):
        sphere.managers.add(active_user)
        url = reverse(name, kwargs={"slug": "no-such-event", "pk": 1})

        response = authenticated_client.post(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("panel:index"),
            messages=[(messages.ERROR, "Event not found.")],
        )


@pytest.mark.django_db
class TestImportViewsIntegrationNotFound:
    @pytest.mark.parametrize("name", _EVENT_NOT_FOUND_POST)
    def test_post_actions_redirect_to_section_for_unknown_integration(
        self, authenticated_client, active_user, sphere, event, name
    ):
        sphere.managers.add(active_user)
        url = reverse(name, kwargs={"slug": event.slug, "pk": 99999})

        response = authenticated_client.post(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_import_url(event),
            messages=[(messages.ERROR, "Import integration not found.")],
        )

    def test_log_tab_renders_empty_for_unknown_integration(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(
            reverse("panel:import-log", kwargs={"slug": event.slug, "pk": 99999})
        )

        assert response.status_code == HTTPStatus.OK
        assert response.template_name == "panel/import-log.html"
        assert response.context_data["active_integration"] is None
