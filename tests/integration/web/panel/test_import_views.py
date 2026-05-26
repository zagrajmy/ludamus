"""Integration tests for the Import / Export panel section.

Import lives in its own section, not under integrations settings; the
integration is just the connection it pulls through.
"""

from __future__ import annotations

import json
from datetime import datetime
from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest
from django.contrib import messages
from django.urls import reverse
from django.utils.timezone import get_current_timezone, localtime

from ludamus.adapters.db.django.models import (
    EventIntegration,
    HostPersonalData,
    PersonalDataField,
    ProposalCategory,
    Session,
    SessionField,
    SessionFieldOption,
    SessionFieldValue,
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

    def test_get_lists_questions_as_recipe_rows_under_a_tab(
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
                "session_columns": ("title", "description"),
                "rows": [
                    {
                        "index": 0,
                        "question": "Title",
                        "selected": "session-field",
                        "field_name": "Title",
                        "field_slug": "title",
                        "field_type": "text",
                        "is_multiple": False,
                        "allow_custom": False,
                        "options": "",
                        "option_windows": [],
                        "option_entities": [],
                        "catchall_name": "",
                        "catchall_slug": "",
                    },
                    {
                        "index": 1,
                        "question": "System",
                        "selected": "session-field",
                        "field_name": "System",
                        "field_slug": "system",
                        "field_type": "text",
                        "is_multiple": False,
                        "allow_custom": False,
                        "options": "",
                        "option_windows": [],
                        "option_entities": [],
                        "catchall_name": "",
                        "catchall_slug": "",
                    },
                ],
            },
        )

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
            response = authenticated_client.get(_tab_url(event, integration))

        assert response.status_code == HTTPStatus.OK
        assert response.context_data["rows"] == [
            {
                "index": 0,
                "question": "Wiek",
                "selected": "session-field",
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
                "catchall_name": "",
                "catchall_slug": "",
            }
        ]
        # The source options reach the rendered setup textarea (not just context).
        assert "do 16\n18+" in response.content.decode()

    def test_get_renders_time_slot_windows_for_a_checkbox_question(
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
            response = authenticated_client.get(_tab_url(event, integration))

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

    def test_get_renders_track_entities_for_a_choice_question(
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
            response = authenticated_client.get(_tab_url(event, integration))

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

    def test_post_saves_time_slot_windows_including_multiple(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        response = authenticated_client.post(
            _tab_url(event, integration),
            data={
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
            messages=[(messages.SUCCESS, "Import recipe saved.")],
        )
        tz = get_current_timezone()
        integration.refresh_from_db()
        target = ImportSettings.model_validate_json(
            integration.settings_json
        ).questions["When"]
        assert target.to == "session.time_slots"
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

    def test_post_saves_a_track_target_with_catchall(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        response = authenticated_client.post(
            _tab_url(event, integration),
            data={
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
            messages=[(messages.SUCCESS, "Import recipe saved.")],
        )
        integration.refresh_from_db()
        target = ImportSettings.model_validate_json(
            integration.settings_json
        ).questions["Suggested"]
        assert target.to == "track"
        # The explicit slug is kept; a blank slug falls back to the name's slug.
        assert target.values == {
            "RPG": EntityRef(name="RPG sessions", slug="rpg"),
            "LARP": EntityRef(name="LARP", slug="larp"),
        }
        assert target.catchall == EntityRef(name="Other", slug="other")

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

    def test_post_saves_recipe_to_settings(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        response = authenticated_client.post(
            _tab_url(event, integration),
            data={
                "question_0": "Title",
                "target_0": "session.title",
                "question_1": "System",
                "target_1": "session-field",
                "newname_1": "System",
                "fieldtype_1": "select",
                "options_1": "D&D\nWarhammer",
                "multiple_1": "on",
                "allowcustom_1": "on",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_tab_url(event, integration),
            messages=[(messages.SUCCESS, "Import recipe saved.")],
        )
        integration.refresh_from_db()
        assert json.loads(integration.settings_json) == {
            "questions": {
                "Title": {
                    "to": "session.title",
                    "ignore": False,
                    "values": {},
                    "catchall": None,
                },
                "System": {
                    "to": "field.system",
                    "ignore": False,
                    "values": {},
                    "catchall": None,
                },
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

    def test_post_honors_an_explicit_field_slug(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        response = authenticated_client.post(
            _tab_url(event, integration),
            data={
                "question_0": "RPG system",
                "target_0": "session-field",
                "newname_0": "System",
                "newslug_0": "rpg-system",
                "fieldtype_0": "text",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_tab_url(event, integration),
            messages=[(messages.SUCCESS, "Import recipe saved.")],
        )
        integration.refresh_from_db()
        assert json.loads(integration.settings_json) == {
            "questions": {
                "RPG system": {
                    "to": "field.rpg-system",
                    "ignore": False,
                    "values": {},
                    "catchall": None,
                }
            },
            "definitions": {
                "personal_fields": {},
                "session_fields": {
                    "rpg-system": {
                        "name": "System",
                        "type": "text",
                        "multiple": False,
                        "allow_custom": False,
                        "options": [],
                    }
                },
            },
        }

    def test_post_saves_a_facilitator_display_name_target(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        response = authenticated_client.post(
            _tab_url(event, integration),
            data={
                "question_0": "How should we credit you?",
                "target_0": "facilitator.display_name",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_tab_url(event, integration),
            messages=[(messages.SUCCESS, "Import recipe saved.")],
        )
        integration.refresh_from_db()
        assert json.loads(integration.settings_json) == {
            "questions": {
                "How should we credit you?": {
                    "to": "facilitator.display_name",
                    "ignore": False,
                    "values": {},
                    "catchall": None,
                }
            },
            "definitions": {"personal_fields": {}, "session_fields": {}},
        }

    def test_post_saves_a_new_personal_field_definition(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        integration = _make_import_integration(
            event, connection_with_secret, display_name="Puller"
        )

        response = authenticated_client.post(
            _tab_url(event, integration),
            data={
                "question_0": "Phone number",
                "target_0": "personal-field",
                "newname_0": "Telefon",
                "fieldtype_0": "text",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_tab_url(event, integration),
            messages=[(messages.SUCCESS, "Import recipe saved.")],
        )
        integration.refresh_from_db()
        assert json.loads(integration.settings_json) == {
            "questions": {
                "Phone number": {
                    "to": "personal.telefon",
                    "ignore": False,
                    "values": {},
                    "catchall": None,
                }
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
            },
        )
