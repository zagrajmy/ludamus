from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from ludamus.mills.konwencik import (
    KONWENCIK_COLUMNS,
    KonwencikExportService,
    KonwencikRow,
)
from ludamus.pacts import AgendaItemDTO, NotFoundError, SpaceDTO, TrackDTO
from ludamus.pacts.konwencik import KonwencikScheduleRepos

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
    repos.events.read.return_value = SimpleNamespace(pk=EVENT_PK, sphere_id=SPHERE_PK)

    integrations = MagicMock()
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
    )
    return SimpleNamespace(
        service=service,
        repos=repos,
        integrations=integrations,
        connections=connections,
        writer=writer,
    )


def _integration(*, settings_json="{}"):
    return SimpleNamespace(
        pk=INTEGRATION_PK,
        event_id=EVENT_PK,
        connection_id=CONNECTION_PK,
        config_json='{"spreadsheet_id": "sheet-1", "tab": "harmonogram"}',
        settings_json=settings_json,
    )


def _written(env):
    return env.writer.write_rows.call_args.kwargs["rows"]


def _cells(env, index=0):
    # One data row as {column key: value}, so assertions name columns.
    return dict(zip(KEYS, _written(env)[_HEADER_ROWS + index], strict=True))


class TestKonwencikRowShape:
    def test_row_fields_are_the_column_keys_in_order(self):
        assert list(KonwencikRow.model_fields) == KEYS

    def test_as_cells_follows_the_column_order(self):
        row = KonwencikRow(
            id="1",
            day="15.08.2026",
            start="10:00",
            end="12:00",
            title="t",
            description="d",
            speaker="s",
            room="r",
        )

        assert dict(zip(KEYS, row.as_cells(), strict=True)) == {
            **dict.fromkeys(KEYS, ""),
            "id": "1",
            "day": "15.08.2026",
            "start": "10:00",
            "end": "12:00",
            "title": "t",
            "description": "d",
            "speaker": "s",
            "room": "r",
        }


class TestKonwencikMatrix:
    def test_writes_key_and_label_header_rows_then_one_row_per_session(self):
        env = _make_service(items=[_item()], spaces=[_space()])

        env.service.run(_integration())

        rows = _written(env)
        assert rows[0] == KEYS
        assert rows[1] == LABELS
        assert len(rows) == _HEADER_ROWS + 1

    def test_writes_the_configured_tab_with_the_decrypted_secret(self):
        env = _make_service(items=[_item()], spaces=[_space()])

        env.service.run(_integration())

        env.connections.read_secret.assert_called_once_with(SPHERE_PK, CONNECTION_PK)
        env.writer.write_rows.assert_called_once_with(
            secret=b"secret",
            spreadsheet_id="sheet-1",
            rows=_written(env),
            tab="harmonogram",
        )

    def test_reports_rows_written(self):
        items = [_item(), _item(pk=2, session_id=SESSION_PK + 1)]
        env = _make_service(items=items)

        outcome = env.service.run(_integration())

        assert outcome.rows_written == len(items)
        assert outcome.sessions_skipped == 0


class TestKonwencikRowBuilder:
    def test_formats_day_and_times_in_the_configured_zone(self):
        # 08:00 UTC is 10:00 in Warsaw during summer time.
        env = _make_service(items=[_item()], spaces=[_space()])

        env.service.run(_integration())

        cells = _cells(env)
        assert cells["id"] == str(SESSION_PK)
        assert cells["day"] == "15.08.2026"
        assert cells["start"] == "10:00"
        assert cells["end"] == "12:00"

    def test_carries_title_description_speaker_and_category(self):
        env = _make_service(items=[_item()], spaces=[_space()])

        env.service.run(_integration())

        cells = _cells(env)
        assert cells["title"] == "Dracula"
        assert cells["description"] == "A long night"
        assert cells["speaker"] == "Alice"
        assert cells["type"] == "RPG session"
        assert not cells["room_position"]

    def test_a_child_space_names_its_immediate_parent(self):
        env = _make_service(
            items=[_item()],
            spaces=[_space(parent_id=40), _space(pk=40, name="Floor 1")],
        )

        env.service.run(_integration())

        assert _cells(env)["room"] == "RPG 1 (Floor 1)"

    def test_a_root_space_has_no_parentheses(self):
        env = _make_service(items=[_item()], spaces=[_space()])

        env.service.run(_integration())

        assert _cells(env)["room"] == "RPG 1"

    def test_unconfigured_settings_leave_icon_colour_and_photo_empty(self):
        env = _make_service(
            items=[_item()],
            spaces=[_space()],
            tracks=[_track()],
            tracks_by_session={SESSION_PK: {20: "Main block"}},
        )

        env.service.run(_integration())

        cells = _cells(env)
        assert cells["block"] == "Main block"
        assert not cells["photo_url"]
        assert not cells["icon"]
        assert not cells["icon_background_color"]

    def test_category_icon_and_track_colour_come_from_settings(self):
        env = _make_service(
            items=[_item()],
            spaces=[_space()],
            tracks=[_track()],
            tracks_by_session={SESSION_PK: {20: "Main block"}},
        )

        env.service.run(
            _integration(
                settings_json=(
                    '{"category_icons": {"9": "fa.gamepad"},'
                    ' "track_colors": {"20": "#ff0000"}}'
                )
            )
        )

        cells = _cells(env)
        assert cells["icon"] == "fa.gamepad"
        assert cells["icon_background_color"] == "#ff0000"

    def test_a_session_field_beats_the_category_icon_default(self):
        env = _make_service(
            items=[_item()],
            spaces=[_space()],
            session_fields=[SimpleNamespace(pk=77, slug="icon-field")],
            field_values={SESSION_PK: {"icon-field": "fa.trophy"}},
        )

        env.service.run(
            _integration(
                settings_json=(
                    '{"category_icons": {"9": "fa.gamepad"}, "icon_field_pk": 77}'
                )
            )
        )

        assert _cells(env)["icon"] == "fa.trophy"

    def test_a_photo_url_field_fills_the_photo_column(self):
        env = _make_service(
            items=[_item()],
            spaces=[_space()],
            session_fields=[SimpleNamespace(pk=78, slug="photo-field")],
            field_values={SESSION_PK: {"photo-field": "https://example.test/a.png"}},
        )

        env.service.run(_integration(settings_json='{"photo_url_field_pk": 78}'))

        assert _cells(env)["photo_url"] == "https://example.test/a.png"


class TestKonwencikExclusions:
    def test_a_soft_deleted_session_produces_no_row(self):
        env = _make_service(items=[_item()], spaces=[_space()], alive=[])

        outcome = env.service.run(_integration())

        assert outcome.rows_written == 0
        assert _written(env) == [KEYS, LABELS]

    def test_an_unscheduled_session_produces_no_row(self):
        # Unscheduled means no agenda item at all, so nothing reaches the mill.
        env = _make_service(items=[], alive=[SESSION_PK])

        assert env.service.run(_integration()).rows_written == 0

    def test_a_session_whose_only_track_is_private_produces_no_row(self):
        env = _make_service(
            items=[_item()],
            spaces=[_space()],
            tracks=[_track(pk=21, name="Internal", is_public=False)],
            tracks_by_session={SESSION_PK: {21: "Internal"}},
        )

        assert env.service.run(_integration()).rows_written == 0

    def test_a_session_with_no_tracks_is_exported_with_an_empty_block(self):
        env = _make_service(
            items=[_item()], spaces=[_space()], tracks=[_track()], tracks_by_session={}
        )

        outcome = env.service.run(_integration())

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

        env.service.run(
            _integration(
                settings_json='{"track_colors": {"20": "#00ff00", "21": "#0000ff"}}'
            )
        )

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

        env.service.run(_integration())

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

        outcome = env.service.run(_integration())

        cells = _cells(env)
        assert outcome.rows_written == 1
        assert cells["day"] == "15.08.2026"
        assert cells["start"] == "22:00"
        assert cells["end"] == "05:00"

    def test_a_session_ending_two_days_later_is_skipped_and_counted(self):
        env = _make_service(
            items=[
                _item(
                    start_time=datetime(2026, 8, 15, 8, 0, tzinfo=UTC),
                    end_time=datetime(2026, 8, 17, 8, 0, tzinfo=UTC),
                )
            ],
            spaces=[_space()],
        )

        outcome = env.service.run(_integration())

        assert outcome.rows_written == 0
        assert outcome.sessions_skipped == 1

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

        outcome = env.service.run(_integration())

        assert outcome.sessions_skipped == 1
        assert "Dracula" in caplog.text


class TestKonwencikExportNow:
    def test_resolves_the_integration_scoped_to_the_event(self):
        env = _make_service(items=[], spaces=[])
        env.integrations.get.return_value = _integration()

        env.service.export_now(
            sphere_id=SPHERE_PK, event_pk=EVENT_PK, pk=INTEGRATION_PK
        )

        env.integrations.get.assert_called_once_with(EVENT_PK, INTEGRATION_PK)

    def test_a_foreign_sphere_raises_without_writing(self):
        env = _make_service(items=[], spaces=[])

        with pytest.raises(NotFoundError):
            env.service.export_now(
                sphere_id=OTHER_SPHERE_PK, event_pk=EVENT_PK, pk=INTEGRATION_PK
            )

        env.integrations.get.assert_not_called()
        env.writer.write_rows.assert_not_called()
