"""Integration tests for the Konwencik export action.

`google.auth` is mocked at the package boundary; the real export service and
the real `GoogleSheetsWriter` run against the fake session, so what lands in
the sheet — and what fails — is exercised end to end.
"""

from __future__ import annotations

import json
from datetime import timedelta
from http import HTTPStatus
from unittest.mock import ANY, MagicMock, patch

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import EventIntegration, SessionField, Track
from ludamus.pacts.chronology import IntegrationImplementationId, IntegrationKind
from ludamus.pacts.konwencik import KonwencikExportSettings, KonwencikNamedItemDTO
from tests.integration.conftest import (
    AgendaItemFactory,
    EventFactory,
    ProposalCategoryFactory,
    SessionFactory,
)
from tests.integration.utils import assert_login_required, assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_not_a_manager,
    panel_context,
)

CONFIG_JSON = json.dumps({"spreadsheet_id": "sheet-1", "tab": "harmonogram"})
_HEADER_ROWS = 2  # machine keys, then Konwencik's own labels
_SCHEDULED = 3


def _settings_url(event) -> str:
    return reverse("panel:event-integration-settings", kwargs={"slug": event.slug})


def _run_url(event, integration) -> str:
    return reverse(
        "panel:konwencik-export-run", kwargs={"slug": event.slug, "pk": integration.pk}
    )


def _google(*, put_ok: bool = True):
    # Metadata carries the configured tab; the values read reports the previous
    # extent; the write is the PUT whose outcome the view reports.
    def get(url: str, **_kwargs: object) -> MagicMock:
        if "/values/" in url:
            return MagicMock(ok=True, json=lambda: {"values": []})
        return MagicMock(
            ok=True, json=lambda: {"sheets": [{"properties": {"title": "harmonogram"}}]}
        )

    session = MagicMock()
    session.get.side_effect = get
    session.put.return_value = MagicMock(
        ok=put_ok, status_code=200 if put_ok else 500, text="" if put_ok else "boom"
    )
    return session


@pytest.fixture(name="google")
def google_fixture():
    session = _google()
    with (
        patch("ludamus.links.google_auth.Credentials.from_service_account_info"),
        patch("ludamus.links.google_auth.AuthorizedSession") as session_cls,
    ):
        session_cls.return_value = session
        yield session


@pytest.fixture(name="export_integration")
def export_integration_fixture(event, connection_with_secret):
    return EventIntegration.objects.create(
        event=event,
        kind=IntegrationKind.EXPORT.value,
        implementation=IntegrationImplementationId.KONWENCIK_SHEET_PUSHER.value,
        connection=connection_with_secret,
        display_name="Konwencik",
        config_json=CONFIG_JSON,
    )


def _track(event, name, *, is_public):
    return Track.objects.create(
        event=event, name=name, slug=name.lower(), is_public=is_public
    )


def _schedule(event, count):
    for _ in range(count):
        session = SessionFactory(category__event=event, event=event)
        AgendaItemFactory(session=session, space__event=event)


@pytest.mark.django_db
class TestKonwencikExportActionView:
    def test_post_redirects_anonymous(self, client, event, export_integration):
        url = _run_url(event, export_integration)

        response = client.post(url)

        assert_login_required(response, url)

    def test_post_redirects_on_unknown_event(self, panel_client, export_integration):
        response = panel_client.post(
            reverse(
                "panel:konwencik-export-run",
                kwargs={"slug": "missing", "pk": export_integration.pk},
            )
        )

        assert_event_not_found(response)

    def test_post_writes_the_schedule_and_reports_the_row_count(
        self, panel_client, event, export_integration, google
    ):
        _schedule(event, _SCHEDULED)

        response = panel_client.post(_run_url(event, export_integration))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Exported 3 sessions.")],
            url=_settings_url(event),
        )
        written = google.put.call_args.kwargs["json"]["values"]
        assert written[0][0] == "id"
        assert written[1][0] == "Id"
        assert len(written) == _HEADER_ROWS + _SCHEDULED

    def test_post_with_nothing_scheduled_writes_only_the_headers(
        self, panel_client, event, export_integration, google
    ):
        response = panel_client.post(_run_url(event, export_integration))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Exported 0 sessions.")],
            url=_settings_url(event),
        )
        assert len(google.put.call_args.kwargs["json"]["values"]) == _HEADER_ROWS

    def test_post_warns_about_sessions_longer_than_a_day(
        self, panel_client, event, export_integration, google
    ):
        session = SessionFactory(category__event=event, event=event)
        item = AgendaItemFactory(session=session, space__event=event)
        item.end_time = item.start_time + timedelta(days=2)
        item.save(update_fields=["end_time"])

        response = panel_client.post(_run_url(event, export_integration))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (messages.SUCCESS, "Exported 0 sessions."),
                (messages.WARNING, "1 session skipped: longer than a day."),
            ],
            url=_settings_url(event),
        )

    def test_post_reports_a_failed_write(self, panel_client, event, export_integration):
        with (
            patch("ludamus.links.google_auth.Credentials.from_service_account_info"),
            patch("ludamus.links.google_auth.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value = _google(put_ok=False)
            response = panel_client.post(_run_url(event, export_integration))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.ERROR,
                    "Export failed: Spreadsheet write request failed with 500: boom",
                )
            ],
            url=_settings_url(event),
        )

    def test_post_with_a_foreign_integration_pk_reports_not_found(
        self, panel_client, event, connection_with_secret, google
    ):
        foreign = EventIntegration.objects.create(
            event=EventFactory(sphere=event.sphere),
            kind=IntegrationKind.EXPORT.value,
            implementation=IntegrationImplementationId.KONWENCIK_SHEET_PUSHER.value,
            connection=connection_with_secret,
            display_name="Elsewhere",
            config_json=CONFIG_JSON,
        )

        response = panel_client.post(_run_url(event, foreign))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Integration not found.")],
            url=_settings_url(event),
        )
        google.put.assert_not_called()


def _settings_page_url(event, integration) -> str:
    return reverse(
        "panel:konwencik-export-settings",
        kwargs={"slug": event.slug, "pk": integration.pk},
    )


def _post_data(*, categories, tracks, photo="", icon="", icons=None, colors=None):
    icons = icons or {}
    colors = colors or {}
    data = {
        "icons-TOTAL_FORMS": str(len(categories)),
        "icons-INITIAL_FORMS": str(len(categories)),
        "colors-TOTAL_FORMS": str(len(tracks)),
        "colors-INITIAL_FORMS": str(len(tracks)),
        "photo_url_field": photo,
        "icon_field": icon,
    }
    for index, category in enumerate(categories):
        data[f"icons-{index}-pk"] = str(category.pk)
        data[f"icons-{index}-icon"] = icons.get(category.pk, "")
    for index, track in enumerate(tracks):
        data[f"colors-{index}-pk"] = str(track.pk)
        data[f"colors-{index}-color"] = colors.get(track.pk, "")
    return data


@pytest.mark.django_db
class TestKonwencikExportSettingsPageView:
    def test_get_redirects_anonymous(self, client, event, export_integration):
        url = _settings_page_url(event, export_integration)

        response = client.get(url)

        assert_login_required(response, url)

    def test_get_redirects_non_manager(
        self, authenticated_client, event, export_integration
    ):
        response = authenticated_client.get(
            _settings_page_url(event, export_integration)
        )

        assert_not_a_manager(response)

    def test_get_renders_a_row_per_category_and_public_track(
        self, panel_client, event, export_integration
    ):
        category = ProposalCategoryFactory(event=event, name="RPG")
        public = _track(event, "Main", is_public=True)
        _track(event, "Internal", is_public=False)

        response = panel_client.get(_settings_page_url(event, export_integration))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/panel/konwencik/settings.html",
            context_data=panel_context(event, active_nav="settings")
            | {
                "integration_pk": export_integration.pk,
                "integration_display_name": "Konwencik",
                "icon_formset": ANY,
                "color_formset": ANY,
                "overrides_form": ANY,
                "category_rows": [
                    {
                        "item": KonwencikNamedItemDTO(pk=category.pk, name="RPG"),
                        "form": ANY,
                    }
                ],
                "track_rows": [
                    {
                        "item": KonwencikNamedItemDTO(pk=public.pk, name="Main"),
                        "form": ANY,
                    }
                ],
            },
        )

    def test_get_with_a_foreign_integration_pk_reports_not_found(
        self, panel_client, event, connection_with_secret
    ):
        foreign = EventIntegration.objects.create(
            event=EventFactory(sphere=event.sphere),
            kind=IntegrationKind.EXPORT.value,
            implementation=IntegrationImplementationId.KONWENCIK_SHEET_PUSHER.value,
            connection=connection_with_secret,
            display_name="Elsewhere",
            config_json=CONFIG_JSON,
        )

        response = panel_client.get(_settings_page_url(event, foreign))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Integration not found.")],
            url=_settings_url(event),
        )

    def test_post_saves_icons_colours_and_overrides(
        self, panel_client, event, export_integration
    ):
        category = ProposalCategoryFactory(event=event, name="RPG")
        track = _track(event, "Main", is_public=True)
        field = SessionField.objects.create(
            event=event, name="Icon", slug="icon", question="Icon?", order=1
        )

        response = panel_client.post(
            _settings_page_url(event, export_integration),
            data=_post_data(
                categories=[category],
                tracks=[track],
                icon=str(field.pk),
                icons={category.pk: "fa.gamepad"},
                colors={track.pk: "#1e88e5"},
            ),
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Export settings saved.")],
            url=_settings_page_url(event, export_integration),
        )
        export_integration.refresh_from_db()
        assert KonwencikExportSettings.model_validate_json(
            export_integration.settings_json
        ) == KonwencikExportSettings(
            category_icons={category.pk: "fa.gamepad"},
            track_colors={track.pk: "#1e88e5"},
            icon_field_pk=field.pk,
        )

    def test_post_rejects_a_track_from_another_event(
        self, panel_client, event, export_integration
    ):
        foreign_track = _track(
            EventFactory(sphere=event.sphere), "Foreign", is_public=True
        )

        response = panel_client.post(
            _settings_page_url(event, export_integration),
            data=_post_data(
                categories=[],
                tracks=[foreign_track],
                colors={foreign_track.pk: "#1e88e5"},
            ),
        )

        assert response.status_code == HTTPStatus.OK
        assert response.context_data["color_formset"].errors == [
            {"pk": ["This does not belong to the event."]}
        ]
        export_integration.refresh_from_db()
        assert export_integration.settings_json in {"", "{}"}

    def test_post_rejects_a_colour_that_is_not_hex(
        self, panel_client, event, export_integration
    ):
        track = _track(event, "Main", is_public=True)

        response = panel_client.post(
            _settings_page_url(event, export_integration),
            data=_post_data(categories=[], tracks=[track], colors={track.pk: "blue"}),
        )

        assert response.status_code == HTTPStatus.OK
        assert response.context_data["color_formset"].errors == [
            {"color": ["Use a hex colour, e.g. #1e88e5."]}
        ]
