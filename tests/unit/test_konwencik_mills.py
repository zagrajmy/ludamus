from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, call
from zoneinfo import ZoneInfo

import pytest
from freezegun import freeze_time
from pydantic import ValidationError

from ludamus.mills.konwencik import (
    ADULT_MIN_AGE,
    EXPORT_LOCK_TIMEOUT,
    KONWENCIK_COLUMNS,
    KonwencikExportService,
)
from ludamus.pacts import AgendaItemDTO, NotFoundError, SpaceDTO
from ludamus.pacts.chronology import IntegrationImplementationId, IntegrationKind
from ludamus.pacts.konwencik import (
    ExportInProgressError,
    KonwencikExportOutcome,
    KonwencikExportSettings,
    KonwencikLastRun,
    KonwencikNamedItemDTO,
    KonwencikScheduleRepos,
    KonwencikSettingsContext,
    KonwencikSkipReason,
)
from ludamus.pacts.sheets import SheetExportError
from tests.unit.factories import track_dto

WARSAW = ZoneInfo("Europe/Warsaw")
NEW_YORK = ZoneInfo("America/New_York")
_NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
_HEADER_ROWS = 2
SPHERE_PK = 7
OTHER_SPHERE_PK = 8
EVENT_PK = 3
CONNECTION_PK = 11
INTEGRATION_PK = 5
SESSION_PK = 100
CATEGORY_PK = 9
KEYS = [key for key, _label in KONWENCIK_COLUMNS]
LABELS = [label for _key, label in KONWENCIK_COLUMNS]


def _item(**overrides):
    defaults = {
        "pk": 1,
        "session_id": SESSION_PK,
        "session_confirmed": True,
        "start_time": datetime(2026, 8, 15, 8, 0, tzinfo=UTC),
        "end_time": datetime(2026, 8, 15, 10, 0, tzinfo=UTC),
        "space_id": 50,
        "space_name": "RPG 1",
        "session_title": "Dracula",
        "session_description": "A long night",
        "presenter_name": "Alice",
        "category_name": "RPG session",
        "category_id": CATEGORY_PK,
    }
    return AgendaItemDTO(**(defaults | overrides))


def _space(**overrides):
    defaults = {
        "pk": 50,
        "name": "RPG 1",
        "parent_id": None,
        "capacity": None,
        "creation_time": _NOW,
        "modification_time": _NOW,
        "order": 0,
        "slug": "rpg-1",
    }
    return SpaceDTO(**(defaults | overrides))


def _track(**overrides):
    return track_dto(
        **{
            "creation_time": _NOW,
            "event_id": EVENT_PK,
            "modification_time": _NOW,
            "name": "Main block",
            "pk": 20,
            "slug": "main-block",
            **overrides,
        }
    )


def _by_event(rows):
    return lambda event_pk: {EVENT_PK: list(rows)}.get(event_pk, [])


def _make_service(
    *,
    items=(),
    spaces=(),
    tracks=(),
    tracks_by_session=None,
    alive=None,
    field_values=None,
    session_fields=(),
    categories=(),
    zone=WARSAW,
):
    repos = SimpleNamespace(
        agenda_items=MagicMock(),
        spaces=MagicMock(),
        tracks=MagicMock(),
        sessions=MagicMock(),
        session_fields=MagicMock(),
        categories=MagicMock(),
        events=MagicMock(),
    )
    memberships = tracks_by_session or {}
    repos.agenda_items.list_by_event.side_effect = _by_event(items)
    repos.spaces.list_by_event.side_effect = _by_event(spaces)
    repos.tracks.list_by_event.side_effect = _by_event(tracks)
    repos.sessions.list_track_names_by_session.side_effect = lambda session_pks: {
        pk: names for pk, names in memberships.items() if pk in session_pks
    }
    repos.sessions.list_alive_pks_by_event.side_effect = _by_event(
        [item.session_id for item in items] if alive is None else alive
    )
    repos.sessions.list_field_values_for_sessions.return_value = field_values or {}
    repos.session_fields.list_by_event.side_effect = _by_event(session_fields)
    repos.categories.list_by_event.side_effect = _by_event(categories)
    repos.events.read.side_effect = {
        EVENT_PK: SimpleNamespace(pk=EVENT_PK, sphere_id=SPHERE_PK)
    }.__getitem__

    transaction = MagicMock()
    integrations = MagicMock()
    integrations.get_for_update.side_effect = lambda _event_pk, _pk: _integration()
    connections = MagicMock()
    connections.read_secret.return_value = b"blob"
    decryptor = MagicMock()
    decryptor.decrypt.return_value = b"secret"
    writer = MagicMock()
    service = KonwencikExportService(
        repos=KonwencikScheduleRepos(**vars(repos)),
        integrations=integrations,
        connections=connections,
        decryptor=decryptor,
        sheet_writer=writer,
        zone=zone,
        transaction=transaction,
    )
    return SimpleNamespace(
        service=service,
        repos=repos,
        integrations=integrations,
        connections=connections,
        decryptor=decryptor,
        writer=writer,
        transaction=transaction,
    )


def _integration(
    *,
    settings_json="{}",
    config_json='{"spreadsheet_id": "sheet-1", "tab": "harmonogram"}',
):
    return SimpleNamespace(
        pk=INTEGRATION_PK,
        event_id=EVENT_PK,
        connection_id=CONNECTION_PK,
        implementation=IntegrationImplementationId.KONWENCIK_SHEET_PUSHER,
        config_json=config_json,
        settings_json=settings_json,
        last_run_json="{}",
    )


def _run(env, settings_json="{}"):
    # `run` re-reads the row it locks, so the fresh copy is the one whose
    # settings drive the export.
    integration = _integration(settings_json=settings_json)
    env.integrations.get_for_update.side_effect = None
    env.integrations.get_for_update.return_value = integration
    return env.service.run(integration)


def _written(env):
    return env.writer.write_rows.call_args.kwargs["rows"]


def _cells(env, index=0):
    # One data row as {column key: value}, so assertions name columns.
    return dict(zip(KEYS, _written(env)[_HEADER_ROWS + index], strict=True))


def _recorded_last_run(env):
    return KonwencikLastRun.model_validate_json(
        env.integrations.update_last_run.call_args.kwargs["last_run_json"]
    )


class TestKonwencikMatrix:
    def test_writes_the_configured_tab_with_the_decrypted_secret(self):
        env = _make_service(items=[_item()], spaces=[_space()])

        _run(env)

        env.repos.events.read.assert_called_once_with(EVENT_PK)
        env.connections.read_secret.assert_called_once_with(SPHERE_PK, CONNECTION_PK)
        env.decryptor.decrypt.assert_called_once_with(b"blob")
        env.writer.write_rows.assert_called_once_with(
            secret=b"secret",
            spreadsheet_id="sheet-1",
            rows=_written(env),
            tab="harmonogram",
        )

    def test_a_connection_without_a_secret_writes_with_an_empty_one(self):
        env = _make_service(items=[_item()], spaces=[_space()])
        env.connections.read_secret.return_value = None

        _run(env)

        env.decryptor.decrypt.assert_not_called()
        assert env.writer.write_rows.call_args.kwargs["secret"] == b""

    def test_a_run_takes_the_lock_writes_and_records_the_outcome(self):
        env = _make_service(items=[_item()], spaces=[_space()])

        outcome = _run(env)

        assert outcome == KonwencikExportOutcome(rows_written=1, skipped={})
        assert (
            env.integrations.get_for_update.call_args_list
            == [call(EVENT_PK, INTEGRATION_PK)] * 2
        )
        locked, released = env.integrations.update_settings.call_args_list
        assert locked.kwargs["event_id"] == EVENT_PK
        assert locked.kwargs["pk"] == INTEGRATION_PK
        lock_time = KonwencikExportSettings.model_validate_json(
            locked.kwargs["settings_json"]
        ).export_lock_time
        assert lock_time is not None
        assert released.kwargs["event_id"] == EVENT_PK
        assert released.kwargs["pk"] == INTEGRATION_PK
        assert (
            KonwencikExportSettings.model_validate_json(
                released.kwargs["settings_json"]
            ).export_lock_time
            is None
        )
        env.integrations.update_last_run.assert_called_once()
        last_run = env.integrations.update_last_run.call_args.kwargs
        assert last_run["event_id"] == EVENT_PK
        assert last_run["pk"] == INTEGRATION_PK
        recorded = KonwencikLastRun.model_validate_json(last_run["last_run_json"])
        assert recorded.ok is True
        assert recorded.rows_written == 1
        assert recorded.skipped == {}
        assert not recorded.error_hint
        assert recorded.time >= lock_time

    def test_a_failed_write_releases_the_lock_and_records_the_error(self):
        env = _make_service(items=[_item()], spaces=[_space()])
        env.writer.write_rows.side_effect = SheetExportError("x" * 600)

        with pytest.raises(SheetExportError):
            _run(env)

        released = env.integrations.update_settings.call_args_list[-1]
        assert (
            KonwencikExportSettings.model_validate_json(
                released.kwargs["settings_json"]
            ).export_lock_time
            is None
        )
        recorded = KonwencikLastRun.model_validate_json(
            env.integrations.update_last_run.call_args.kwargs["last_run_json"]
        )
        assert recorded.ok is False
        assert recorded.rows_written == 0
        assert recorded.error_hint == "x" * 500

    def test_a_blank_settings_blob_reads_as_defaults(self):
        env = _make_service(items=[_item()], spaces=[_space()])

        outcome = _run(env, "")

        assert outcome == KonwencikExportOutcome(rows_written=1, skipped={})

    def test_rows_are_ordered_by_start_then_space_then_session(self):
        env = _make_service(
            items=[
                _item(pk=2, session_id=102, space_name="RPG 2"),
                _item(pk=3, session_id=103),
                _item(pk=1, session_id=101),
                _item(
                    pk=4,
                    session_id=104,
                    space_name="RPG 9",
                    start_time=datetime(2026, 8, 15, 7, 0, tzinfo=UTC),
                ),
            ],
            spaces=[_space()],
        )

        _run(env)

        assert [row[0] for row in _written(env)[_HEADER_ROWS:]] == [
            "104",
            "101",
            "103",
            "102",
        ]


class TestKonwencikRowBuilder:
    def test_a_row_carries_every_column_in_the_configured_zone(self):
        # 08:00 UTC is 10:00 in Warsaw during summer time.
        env = _make_service(items=[_item()], spaces=[_space()])

        _run(env)

        assert _cells(env) == {
            "id": str(SESSION_PK),
            "day": "15.08.2026",
            "start": "10:00",
            "end": "12:00",
            "title": "Dracula",
            "description": "A long night",
            "speaker": "Alice",
            "room": "RPG 1",
            "room_position": "",
            "block": "",
            "type": "RPG session",
            "photo_url": "",
            "icon": "",
            "icon_background_color": "",
        }

    def test_times_follow_the_service_zone_not_the_hosts(self):
        env = _make_service(
            items=[_item()], spaces=[_space()], zone=timezone(timedelta(hours=-3))
        )

        _run(env)

        cells = _cells(env)
        assert (cells["start"], cells["end"]) == ("05:00", "07:00")

    def test_an_adults_only_session_carries_the_tag_in_its_title(self):
        # Konwencik has no minimum-age column, so the title is the only place
        # the restriction can be stated.
        env = _make_service(
            items=[_item(session_min_age=ADULT_MIN_AGE)], spaces=[_space()]
        )

        _run(env)

        assert _cells(env)["title"] == "[18+] Dracula"

    def test_a_child_space_names_its_immediate_parent(self):
        env = _make_service(
            items=[_item()],
            spaces=[_space(parent_id=40), _space(pk=40, name="Floor 1")],
        )

        _run(env)

        assert _cells(env)["room"] == "RPG 1 (Floor 1)"

    def test_a_space_missing_from_the_list_keeps_the_item_name(self):
        env = _make_service(items=[_item()], spaces=[])

        _run(env)

        assert _cells(env)["room"] == "RPG 1"

    def test_an_uncategorised_session_has_an_empty_type_and_icon(self):
        env = _make_service(
            items=[_item(category_id=None, category_name=None)], spaces=[_space()]
        )

        _run(env, '{"category_icons": {"9": "fa.gamepad"}}')

        cells = _cells(env)
        assert (cells["type"], cells["icon"]) == ("", "")

    def test_a_session_field_beats_the_category_icon_default(self):
        env = _make_service(
            items=[_item()],
            spaces=[_space()],
            session_fields=[SimpleNamespace(pk=77, slug="icon-field")],
            field_values={SESSION_PK: {"icon-field": "fa.trophy"}},
        )

        _run(env, '{"category_icons": {"9": "fa.gamepad"}, "icon_field_pk": 77}')

        assert _cells(env)["icon"] == "fa.trophy"
        env.repos.sessions.list_field_values_for_sessions.assert_called_once_with(
            [SESSION_PK], [77]
        )

    def test_a_non_text_answer_falls_back_to_the_category_icon(self):
        env = _make_service(
            items=[_item()],
            spaces=[_space()],
            session_fields=[SimpleNamespace(pk=77, slug="icon-field")],
            field_values={SESSION_PK: {"icon-field": ["fa.trophy", "fa.dice"]}},
        )

        _run(env, '{"category_icons": {"9": "fa.gamepad"}, "icon_field_pk": 77}')

        assert _cells(env)["icon"] == "fa.gamepad"

    def test_a_photo_field_answer_fills_the_photo_column(self):
        env = _make_service(
            items=[_item()],
            spaces=[_space()],
            session_fields=[SimpleNamespace(pk=78, slug="photo")],
            field_values={SESSION_PK: {"photo": "https://img.example/dracula.jpg"}},
        )

        _run(env, '{"photo_url_field_pk": 78}')

        assert _cells(env)["photo_url"] == "https://img.example/dracula.jpg"

    def test_no_configured_field_leaves_the_value_store_alone(self):
        env = _make_service(items=[_item()], spaces=[_space()])

        _run(env)

        env.repos.sessions.list_field_values_for_sessions.assert_not_called()


class TestKonwencikExclusions:
    def test_a_soft_deleted_session_produces_no_row(self):
        env = _make_service(items=[_item()], spaces=[_space()], alive=[])

        outcome = _run(env)

        assert outcome.rows_written == 0
        assert _written(env) == [KEYS, LABELS]

    def test_sessions_whose_every_track_is_private_produce_no_rows(self, caplog):
        env = _make_service(
            items=[
                _item(),
                _item(pk=2, session_id=101, session_title="Nosferatu"),
                _item(
                    pk=3,
                    session_id=102,
                    start_time=datetime(2026, 8, 15, 11, 0, tzinfo=UTC),
                    end_time=datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
                ),
            ],
            spaces=[_space()],
            tracks=[_track(pk=21, name="Internal", is_public=False)],
            tracks_by_session={SESSION_PK: {21: "Internal"}, 101: {21: "Internal"}},
        )

        outcome = _run(env)

        # Counted under its own reason: marking a track internal takes its
        # whole programme out of Konwencik, which the panel has to say.
        assert outcome == KonwencikExportOutcome(
            rows_written=1, skipped={KonwencikSkipReason.INTERNAL_TRACKS: 2}
        )
        assert _cells(env)["id"] == "102"
        assert caplog.messages == [
            "Konwencik export skipped session 100 (Dracula): every block internal",
            "Konwencik export skipped session 101 (Nosferatu): every block internal",
        ]

    def test_a_session_with_no_tracks_is_exported_with_an_empty_block(self):
        env = _make_service(
            items=[_item()], spaces=[_space()], tracks=[_track()], tracks_by_session={}
        )

        outcome = _run(env)

        assert outcome.rows_written == 1
        assert not _cells(env)["block"]
        assert not _cells(env)["icon_background_color"]


class TestKonwencikTrackChoice:
    def test_two_public_tracks_take_the_alphabetically_first(self):
        env = _make_service(
            items=[_item()],
            spaces=[_space()],
            # Repository order is Track.Meta.ordering, i.e. by name.
            tracks=[_track(pk=21, name="Alpha"), _track(pk=20, name="Beta")],
            tracks_by_session={SESSION_PK: {20: "Beta", 21: "Alpha"}},
        )

        _run(env, '{"track_colors": {"20": "#00ff00", "21": "#0000ff"}}')

        cells = _cells(env)
        assert cells["block"] == "Alpha"
        assert cells["icon_background_color"] == "#0000ff"

    def test_a_public_and_a_private_track_take_the_public_one(self):
        env = _make_service(
            items=[_item()],
            spaces=[_space()],
            tracks=[
                _track(pk=21, name="Alpha", is_public=False),
                _track(pk=20, name="Beta"),
            ],
            tracks_by_session={SESSION_PK: {20: "Beta", 21: "Alpha"}},
        )

        _run(env)

        cells = _cells(env)
        assert cells["block"] == "Beta"
        assert not cells["icon_background_color"]


class TestKonwencikMidnight:
    def test_a_session_across_midnight_is_one_row_ending_before_it_starts(self):
        env = _make_service(
            items=[
                _item(
                    start_time=datetime(2026, 8, 15, 20, 0, tzinfo=UTC),
                    end_time=datetime(2026, 8, 16, 3, 0, tzinfo=UTC),
                )
            ],
            spaces=[_space()],
        )

        outcome = _run(env)

        cells = _cells(env)
        assert outcome.rows_written == 1
        assert cells["day"] == "15.08.2026"
        assert cells["start"] == "22:00"
        assert cells["end"] == "05:00"

    def test_full_day_sessions_are_skipped_logged_and_counted(self, caplog):
        day_long = {
            "start_time": datetime(2026, 8, 15, 8, 0, tzinfo=UTC),
            "end_time": datetime(2026, 8, 16, 8, 0, tzinfo=UTC),
        }
        env = _make_service(
            items=[
                _item(**day_long),
                _item(pk=2, session_id=101, session_title="Nosferatu", **day_long),
                _item(
                    pk=3,
                    session_id=102,
                    start_time=datetime(2026, 8, 15, 11, 0, tzinfo=UTC),
                    end_time=datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
                ),
            ],
            spaces=[_space()],
        )

        outcome = _run(env)

        assert outcome == KonwencikExportOutcome(
            rows_written=1, skipped={KonwencikSkipReason.TOO_LONG: 2}
        )
        assert _cells(env)["id"] == "102"
        assert caplog.messages == [
            "Konwencik export skipped session 100 (Dracula): longer than a day",
            "Konwencik export skipped session 101 (Nosferatu): longer than a day",
        ]
        assert _recorded_last_run(env).skipped == {KonwencikSkipReason.TOO_LONG: 2}

    def test_the_day_limit_reads_the_wall_clock_of_the_configured_zone(self):
        # 23.5 hours of UTC, but New York's clocks skip an hour that night, so
        # the sheet would show an end later than the start on the next day,
        # which Konwencik cannot express.
        env = _make_service(
            items=[
                _item(
                    start_time=datetime(2026, 3, 8, 5, 30, tzinfo=UTC),
                    end_time=datetime(2026, 3, 9, 5, 0, tzinfo=UTC),
                )
            ],
            spaces=[_space()],
            zone=NEW_YORK,
        )
        env.integrations.get.return_value = _integration()

        context = env.service.get_settings_context(
            sphere_id=SPHERE_PK, event_pk=EVENT_PK, pk=INTEGRATION_PK
        )
        outcome = _run(env)

        assert context.programme_combinations == []
        assert outcome.skipped == {KonwencikSkipReason.TOO_LONG: 1}


class TestKonwencikUpdateStyles:
    def test_patches_fresh_settings_without_clearing_lock(self):
        env = _make_service(
            tracks=[_track()], categories=[SimpleNamespace(pk=CATEGORY_PK)]
        )
        env.integrations.get.return_value = _integration()
        fresh = KonwencikExportSettings(
            track_colors={20: "#203b50", 21: "#02897e"},
            category_icons={CATEGORY_PK: "fa.gamepad"},
            sync_enabled=True,
            icon_field_pk=31,
            photo_url_field_pk=32,
            export_lock_time=_NOW,
        )
        env.integrations.get_for_update.side_effect = None
        env.integrations.get_for_update.return_value = _integration(
            settings_json=fresh.model_dump_json()
        )

        result = env.service.update_styles(
            sphere_id=SPHERE_PK,
            event_pk=EVENT_PK,
            pk=INTEGRATION_PK,
            track_colors={20: "#2c4d9b"},
            category_icons={CATEGORY_PK: ""},
        )

        fresh.track_colors[20] = "#2c4d9b"
        fresh.category_icons = {}
        assert result == fresh
        env.integrations.get.assert_called_once_with(EVENT_PK, INTEGRATION_PK)
        env.integrations.get_for_update.assert_called_once_with(
            EVENT_PK, INTEGRATION_PK
        )
        env.integrations.update_settings.assert_called_once_with(
            event_id=EVENT_PK, pk=INTEGRATION_PK, settings_json=fresh.model_dump_json()
        )

    def test_a_blank_blob_takes_the_patch_and_ignores_a_removal(self):
        env = _make_service(
            tracks=[_track()], categories=[SimpleNamespace(pk=CATEGORY_PK)]
        )
        env.integrations.get.return_value = _integration()
        env.integrations.get_for_update.side_effect = None
        env.integrations.get_for_update.return_value = _integration(settings_json="")

        result = env.service.update_styles(
            sphere_id=SPHERE_PK,
            event_pk=EVENT_PK,
            pk=INTEGRATION_PK,
            track_colors={20: "#2c4d9b"},
            category_icons={CATEGORY_PK: ""},
        )

        assert result == KonwencikExportSettings(track_colors={20: "#2c4d9b"})

    @pytest.mark.parametrize(
        ("colors", "icons"), (({999: "#203b50"}, {}), ({}, {999: "fa.gamepad"}))
    )
    def test_foreign_ids_reject_whole_patch(self, colors, icons):
        env = _make_service(tracks=[_track()])
        env.integrations.get.return_value = _integration()

        with pytest.raises(NotFoundError):
            env.service.update_styles(
                sphere_id=SPHERE_PK,
                event_pk=EVENT_PK,
                pk=INTEGRATION_PK,
                track_colors={20: "#203b50", **colors},
                category_icons=icons,
            )

        env.integrations.update_settings.assert_not_called()


class TestKonwencikSettingsContext:
    def test_collects_the_choices_the_settings_page_offers(self):
        public, private = _track(), _track(pk=21, name="Hidden", is_public=False)
        item = _item()
        env = _make_service(
            items=[item],
            tracks=[public, private],
            tracks_by_session={item.session_id: {public.pk: public.name}},
            session_fields=[SimpleNamespace(pk=31, name="Photo")],
            categories=[SimpleNamespace(pk=CATEGORY_PK, name="RPG")],
        )
        last_run = KonwencikLastRun(time=_NOW, ok=True, rows_written=3)
        integration = _integration(settings_json='{"sync_enabled": true}')
        integration.last_run_json = last_run.model_dump_json()
        env.integrations.get.return_value = integration

        context = env.service.get_settings_context(
            sphere_id=SPHERE_PK, event_pk=EVENT_PK, pk=INTEGRATION_PK
        )

        assert context == KonwencikSettingsContext(
            categories=[KonwencikNamedItemDTO(pk=CATEGORY_PK, name="RPG")],
            tracks=[KonwencikNamedItemDTO(pk=public.pk, name=public.name)],
            session_fields=[KonwencikNamedItemDTO(pk=31, name="Photo")],
            settings=KonwencikExportSettings(sync_enabled=True),
            last_run=last_run,
            programme_combinations=[(CATEGORY_PK, public.pk)],
        )
        env.repos.events.read.assert_called_once_with(EVENT_PK)
        env.integrations.get.assert_called_once_with(EVENT_PK, INTEGRATION_PK)
        env.repos.categories.list_by_event.assert_called_once_with(EVENT_PK)
        env.repos.session_fields.list_by_event.assert_called_once_with(EVENT_PK)
        env.repos.sessions.list_alive_pks_by_event.assert_called_once_with(EVENT_PK)
        env.repos.agenda_items.list_by_event.assert_called_once_with(EVENT_PK)
        env.repos.sessions.list_track_names_by_session.assert_called_once_with(
            [item.session_id]
        )

    def test_a_row_never_saved_or_run_has_defaults_and_no_last_run(self):
        env = _make_service()
        integration = _integration(settings_json="")
        integration.last_run_json = ""
        env.integrations.get.return_value = integration

        context = env.service.get_settings_context(
            sphere_id=SPHERE_PK, event_pk=EVENT_PK, pk=INTEGRATION_PK
        )

        assert context.settings == KonwencikExportSettings()
        assert context.last_run is None
        assert context.programme_combinations == []


class TestKonwencikExportNow:
    def test_runs_the_integration_the_panel_names(self):
        env = _make_service(items=[_item()], spaces=[_space()])
        env.integrations.get.return_value = _integration()

        outcome = env.service.export_now(
            sphere_id=SPHERE_PK, event_pk=EVENT_PK, pk=INTEGRATION_PK
        )

        assert outcome == KonwencikExportOutcome(rows_written=1, skipped={})
        env.integrations.get.assert_called_once_with(EVENT_PK, INTEGRATION_PK)

    def test_another_implementation_in_the_same_event_is_not_found(self):
        # Panel access proves the sphere, not that this pk is the export's.
        # An importer's row must not be run against a sheet, nor have its
        # settings replaced by the Konwencik page's.
        env = _make_service(items=[], spaces=[])
        importer = _integration()
        importer.implementation = IntegrationImplementationId.GOOGLE_PROPOSAL_PULLER
        env.integrations.get.return_value = importer

        with pytest.raises(NotFoundError):
            env.service.export_now(
                sphere_id=SPHERE_PK, event_pk=EVENT_PK, pk=INTEGRATION_PK
            )

        env.writer.write_rows.assert_not_called()
        env.integrations.update_settings.assert_not_called()

    def test_a_foreign_sphere_raises_without_writing(self):
        env = _make_service(items=[], spaces=[])

        with pytest.raises(NotFoundError):
            env.service.export_now(
                sphere_id=OTHER_SPHERE_PK, event_pk=EVENT_PK, pk=INTEGRATION_PK
            )

        env.integrations.get.assert_not_called()
        env.writer.write_rows.assert_not_called()


def _locked_integration(*, held_ago):
    lock = (datetime.now(UTC) - held_ago).isoformat()
    return _integration(settings_json=f'{{"export_lock_time": "{lock}"}}')


class TestKonwencikLock:
    def test_a_run_takes_the_lock_and_releases_it(self):
        env = _make_service(items=[], spaces=[])

        _run(env)

        saved = [
            KonwencikExportSettings.model_validate_json(call.kwargs["settings_json"])
            for call in env.integrations.update_settings.call_args_list
        ]
        assert saved[0].export_lock_time is not None
        assert saved[-1].export_lock_time is None

    def test_a_stale_lock_is_taken_over(self):
        env = _make_service(items=[], spaces=[])
        env.integrations.get_for_update.side_effect = lambda _event_pk, _pk: (
            _locked_integration(held_ago=timedelta(hours=2))
        )

        env.service.run(_integration())

        env.writer.write_rows.assert_called_once()

    @freeze_time(_NOW)
    def test_a_lock_held_for_exactly_the_timeout_is_taken_over(self):
        env = _make_service(items=[], spaces=[])
        env.integrations.get_for_update.side_effect = lambda _event_pk, _pk: (
            _locked_integration(held_ago=EXPORT_LOCK_TIMEOUT)
        )

        env.service.run(_integration())

        env.writer.write_rows.assert_called_once()

    def test_a_failure_that_is_not_a_sheet_error_still_releases_the_lock(self):
        # An unparsable config blob raises before the writer is reached. The
        # lock has to come off anyway, or the integration wedges until it ages
        # out with no last_run explaining why.
        env = _make_service(items=[], spaces=[])

        with pytest.raises(ValidationError):
            env.service.run(_integration(config_json="not json"))

        saved = [
            KonwencikExportSettings.model_validate_json(call.kwargs["settings_json"])
            for call in env.integrations.update_settings.call_args_list
        ]
        assert saved[-1].export_lock_time is None
        assert (
            KonwencikLastRun.model_validate_json(
                env.integrations.update_last_run.call_args.kwargs["last_run_json"]
            ).ok
            is False
        )


def _sync_integration(**overrides):
    integration = _integration(settings_json='{"sync_enabled": true}')
    for key, value in overrides.items():
        setattr(integration, key, value)
    return integration


class TestKonwencikSweep:
    def test_keeps_going_past_an_unreadable_settings_blob(self):
        # The blob is parsed inside the per-integration guard, so one bad row
        # costs its own export and not the rest of the sweep.
        env = _make_service(items=[], spaces=[])
        env.integrations.list_by_kind.return_value = [
            _sync_integration(pk=1, settings_json='{"sync_enabled": "maybe"}'),
            _sync_integration(pk=2),
        ]

        assert env.service.run_sweep(now=_NOW) == 1

    def test_keeps_going_after_one_integration_fails(self, caplog):
        env = _make_service(items=[], spaces=[])
        healthy = [_sync_integration(pk=2), _sync_integration(pk=3)]
        env.integrations.list_by_kind.return_value = [_sync_integration(pk=1), *healthy]
        env.writer.write_rows.side_effect = [SheetExportError("denied"), None, None]

        assert env.service.run_sweep(now=_NOW) == len(healthy)
        assert caplog.messages == ["Konwencik sweep skipped integration 1: denied"]

    def test_asks_only_for_events_that_have_not_long_finished(self):
        env = _make_service(items=[], spaces=[])
        env.integrations.list_by_kind.return_value = []

        env.service.run_sweep(now=_NOW)

        env.integrations.list_by_kind.assert_called_once_with(
            IntegrationKind.EXPORT, event_ended_after=_NOW - timedelta(days=1)
        )

    def test_skips_other_implementations_and_disabled_syncs(self, caplog):
        env = _make_service(items=[], spaces=[])
        env.integrations.list_by_kind.return_value = [
            _sync_integration(
                pk=1, implementation=IntegrationImplementationId.GOOGLE_PROPOSAL_PULLER
            ),
            _integration(settings_json=""),
            _sync_integration(pk=3),
        ]

        assert env.service.run_sweep(now=_NOW) == 1
        env.writer.write_rows.assert_called_once()
        assert caplog.records == []


class TestKonwencikLockHeld:
    def test_a_fresh_lock_refuses_a_second_run_without_writing(self):
        env = _make_service(items=[], spaces=[])
        env.integrations.get_for_update.side_effect = lambda _event_pk, _pk: (
            _locked_integration(held_ago=timedelta(minutes=1))
        )

        with pytest.raises(ExportInProgressError):
            env.service.run(_integration())

        env.writer.write_rows.assert_not_called()
        env.integrations.update_last_run.assert_not_called()


TRACK_PK = 20
PRIVATE_TRACK_PK = 21
FIELD_PK = 77
OTHER_CATEGORY_PK = 10


def _settings_env(**kwargs):
    return _make_service(
        categories=[SimpleNamespace(pk=CATEGORY_PK, name="RPG")],
        session_fields=[SimpleNamespace(pk=FIELD_PK, name="Icon", slug="icon")],
        **kwargs,
    )


def _saved_settings(env):
    return KonwencikExportSettings.model_validate_json(
        env.integrations.update_settings.call_args.kwargs["settings_json"]
    )


class TestKonwencikProgrammeCombinations:
    def test_programme_combinations_follow_the_export_rules(self):
        # One pair per (category, public block) that would reach the sheet:
        # dead sessions, uncategorised items, day-long items and internal-only
        # blocks are left out, and duplicates collapse.
        env = _settings_env(
            items=[
                _item(pk=4, session_id=104, category_id=None),
                _item(pk=1, session_id=101),
                _item(pk=2, session_id=102),
                _item(pk=3, session_id=103),
                _item(pk=5, session_id=105),
                _item(
                    pk=6,
                    session_id=106,
                    category_id=OTHER_CATEGORY_PK,
                    end_time=datetime(2026, 8, 16, 8, 0, tzinfo=UTC),
                ),
                _item(pk=7, session_id=107, category_id=OTHER_CATEGORY_PK),
                _item(pk=8, session_id=108, category_id=OTHER_CATEGORY_PK),
            ],
            tracks=[
                _track(),
                _track(pk=PRIVATE_TRACK_PK, name="Crew", is_public=False),
            ],
            tracks_by_session={
                101: {TRACK_PK: "Main block"},
                102: {TRACK_PK: "Main block"},
                105: {PRIVATE_TRACK_PK: "Crew"},
                108: {TRACK_PK: "Main block"},
            },
            alive=[101, 102, 103, 104, 105, 106, 107],
        )
        env.integrations.get.return_value = _integration()

        context = env.service.get_settings_context(
            sphere_id=SPHERE_PK, event_pk=EVENT_PK, pk=INTEGRATION_PK
        )

        assert context.programme_combinations == [
            (CATEGORY_PK, TRACK_PK),
            (CATEGORY_PK, None),
            (OTHER_CATEGORY_PK, None),
        ]


class TestKonwencikSaveSettings:
    def test_keeps_only_ids_the_page_offered_and_clears_the_lock(self):
        env = _settings_env(tracks=[_track()])
        env.integrations.get.return_value = _integration()

        env.service.save_settings(
            sphere_id=SPHERE_PK,
            event_pk=EVENT_PK,
            pk=INTEGRATION_PK,
            settings=KonwencikExportSettings(
                category_icons={CATEGORY_PK: "fa.gamepad", OTHER_CATEGORY_PK: "fa.x"},
                track_colors={TRACK_PK: "#abc", PRIVATE_TRACK_PK: "#def"},
                photo_url_field_pk=FIELD_PK + 1,
                icon_field_pk=FIELD_PK,
                sync_enabled=True,
                export_lock_time=_NOW,
            ),
        )

        env.integrations.get.assert_called_once_with(EVENT_PK, INTEGRATION_PK)
        env.integrations.update_settings.assert_called_once_with(
            event_id=EVENT_PK,
            pk=INTEGRATION_PK,
            settings_json=KonwencikExportSettings(
                category_icons={CATEGORY_PK: "fa.gamepad"},
                track_colors={TRACK_PK: "#abc"},
                icon_field_pk=FIELD_PK,
                sync_enabled=True,
            ).model_dump_json(),
        )

    def test_an_empty_value_removes_the_style(self):
        env = _settings_env(tracks=[_track()])
        env.integrations.get.return_value = _integration()

        env.service.save_settings(
            sphere_id=SPHERE_PK,
            event_pk=EVENT_PK,
            pk=INTEGRATION_PK,
            settings=KonwencikExportSettings(
                category_icons={CATEGORY_PK: ""}, track_colors={TRACK_PK: ""}
            ),
        )

        saved = _saved_settings(env)
        assert saved.category_icons == {}
        assert saved.track_colors == {}
