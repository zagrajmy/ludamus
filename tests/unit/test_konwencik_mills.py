from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from ludamus.mills.konwencik import (
    ADULT_MIN_AGE,
    KONWENCIK_COLUMNS,
    KonwencikExportService,
)
from ludamus.pacts import AgendaItemDTO, NotFoundError, SpaceDTO, TrackDTO
from ludamus.pacts.chronology import IntegrationImplementationId, IntegrationKind
from ludamus.pacts.konwencik import (
    KonwencikExportSettings,
    KonwencikLastRun,
    KonwencikScheduleRepos,
    KonwencikSkipReason,
)
from ludamus.pacts.sheets import SheetExportError

WARSAW = ZoneInfo("Europe/Warsaw")
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
    defaults = {
        "pk": 20,
        "name": "Main block",
        "slug": "main-block",
        "is_public": True,
        "event_id": EVENT_PK,
        "creation_time": _NOW,
        "modification_time": _NOW,
    }
    return TrackDTO(**(defaults | overrides))


def _make_service(
    *,
    items=(),
    spaces=(),
    tracks=(),
    tracks_by_session=None,
    alive=None,
    field_values=None,
    session_fields=(),
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
    repos.agenda_items.list_by_event.return_value = list(items)
    repos.spaces.list_by_event.return_value = list(spaces)
    repos.tracks.list_by_event.return_value = list(tracks)
    repos.sessions.list_track_names_by_session.return_value = tracks_by_session or {}
    repos.sessions.list_alive_pks_by_event.return_value = (
        [item.session_id for item in items] if alive is None else alive
    )
    repos.sessions.list_field_values_for_sessions.return_value = field_values or {}
    repos.session_fields.list_by_event.return_value = list(session_fields)
    repos.categories.list_by_event.return_value = []
    repos.events.read.return_value = SimpleNamespace(pk=EVENT_PK, sphere_id=SPHERE_PK)

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
        zone=WARSAW,
        transaction=transaction,
    )
    return SimpleNamespace(
        service=service,
        repos=repos,
        integrations=integrations,
        connections=connections,
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


class TestKonwencikRowBuilder:
    def test_formats_day_and_times_in_the_configured_zone(self):
        # 08:00 UTC is 10:00 in Warsaw during summer time.
        env = _make_service(items=[_item()], spaces=[_space()])

        _run(env)

        cells = _cells(env)
        assert cells["id"] == str(SESSION_PK)
        assert cells["day"] == "15.08.2026"
        assert cells["start"] == "10:00"
        assert cells["end"] == "12:00"

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

    def test_a_session_field_beats_the_category_icon_default(self):
        env = _make_service(
            items=[_item()],
            spaces=[_space()],
            session_fields=[SimpleNamespace(pk=77, slug="icon-field")],
            field_values={SESSION_PK: {"icon-field": "fa.trophy"}},
        )

        _run(env, '{"category_icons": {"9": "fa.gamepad"}, "icon_field_pk": 77}')

        assert _cells(env)["icon"] == "fa.trophy"


class TestKonwencikExclusions:
    def test_a_soft_deleted_session_produces_no_row(self):
        env = _make_service(items=[_item()], spaces=[_space()], alive=[])

        outcome = _run(env)

        assert outcome.rows_written == 0
        assert _written(env) == [KEYS, LABELS]

    def test_a_session_whose_only_track_is_private_produces_no_row(self):
        env = _make_service(
            items=[_item()],
            spaces=[_space()],
            tracks=[_track(pk=21, name="Internal", is_public=False)],
            tracks_by_session={SESSION_PK: {21: "Internal"}},
        )

        outcome = _run(env)

        assert outcome.rows_written == 0
        # Counted under its own reason: marking a track internal takes its
        # whole programme out of Konwencik, which the panel has to say.
        assert outcome.skipped == {KonwencikSkipReason.INTERNAL_TRACKS: 1}

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

        assert _cells(env)["block"] == "Beta"


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

    def test_a_full_day_session_is_skipped_and_logged(self, caplog):
        env = _make_service(
            items=[
                _item(
                    start_time=datetime(2026, 8, 15, 8, 0, tzinfo=UTC),
                    end_time=datetime(2026, 8, 16, 8, 0, tzinfo=UTC),
                )
            ],
            spaces=[_space()],
        )

        outcome = _run(env)

        assert outcome.skipped == {KonwencikSkipReason.TOO_LONG: 1}
        assert "Dracula" in caplog.text


class TestKonwencikUpdateStyles:
    def test_patches_fresh_settings_without_clearing_lock(self):
        env = _make_service(tracks=[_track()])
        env.repos.categories.list_by_event.return_value = [
            SimpleNamespace(pk=CATEGORY_PK)
        ]
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


class TestKonwencikExportNow:
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

    def test_keeps_going_after_one_integration_fails(self):
        env = _make_service(items=[], spaces=[])
        env.integrations.list_by_kind.return_value = [
            _sync_integration(pk=1),
            _sync_integration(pk=2),
        ]
        env.writer.write_rows.side_effect = [SheetExportError("denied"), None]

        assert env.service.run_sweep(now=_NOW) == 1

    def test_asks_only_for_events_that_have_not_long_finished(self):
        env = _make_service(items=[], spaces=[])
        env.integrations.list_by_kind.return_value = []

        env.service.run_sweep(now=_NOW)

        call = env.integrations.list_by_kind.call_args
        assert call.args == (IntegrationKind.EXPORT,)
        assert call.kwargs["event_ended_after"] == _NOW - timedelta(days=1)
