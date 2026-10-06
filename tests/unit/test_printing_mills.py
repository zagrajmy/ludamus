from contextlib import nullcontext
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from ludamus.mills.printing import (
    MAX_DOOR_CARD_ENTRIES_PER_SHEET,
    MAX_SESSION_LIST_DESCRIBED_ROWS_PER_SHEET,
    MAX_SESSION_LIST_ROWS_PER_SHEET,
    MAX_TIMETABLE_ROWS_PER_PAGE,
    PRINTABLES_REMINDER_LEAD_TIME,
    PrintablesReminderService,
    PrintMaterialsService,
)
from ludamus.pacts import AgendaItemDTO, SpaceDTO, TrackDTO
from ludamus.pacts.printing import PrintablesReminderDTO, PrintOptionDTO, PrintQueryDTO
from tests.unit.factories import event_dto


def _event():
    return event_dto(description="Konwent dla nerdów")


def _space(pk, name, order, parent_id=None):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return SpaceDTO(
        parent_id=parent_id,
        capacity=20,
        creation_time=now,
        modification_time=now,
        name=name,
        order=order,
        programme_order=order,
        pk=pk,
        slug=name.lower(),
    )


def _item(
    pk,
    space_id,
    start_hour,
    end_hour,
    *,
    title,
    confirmed,
    description="",
    day=1,
    space_name="",
):
    return AgendaItemDTO(
        pk=pk,
        schedule_confirmed=confirmed,
        start_time=datetime(2026, 6, day, start_hour, 0, tzinfo=UTC),
        end_time=datetime(2026, 6, day, end_hour, 0, tzinfo=UTC),
        space_id=space_id,
        space_name=space_name,
        session_title=title,
        session_description=description,
        presenter_name="GM",
    )


EVENT_PK = 1
TRACK_PK = 5


class _Events:
    def __init__(self, event):
        self._events = {event.pk: event}

    def read(self, pk):
        return self._events[pk]


class _Spaces:
    def __init__(self, rows):
        self._rows = {EVENT_PK: list(rows)}

    def list_by_event(self, event_pk):
        return list(self._rows[event_pk])


def _public(rows, *, public_only):
    return [row for row in rows if row.schedule_confirmed or not public_only]


class _AgendaItems:
    def __init__(self, rows, track_rows):
        self._by_event = {EVENT_PK: list(rows)}
        self._by_track = {TRACK_PK: list(track_rows)}

    def list_by_event(self, event_pk, *, public_only=False):
        return _public(self._by_event[event_pk], public_only=public_only)

    def list_by_track(self, track_pk, *, public_only=False):
        return _public(self._by_track[track_pk], public_only=public_only)


class _Tracks:
    def __init__(self, tracks=(), space_pks=()):
        self._tracks = {EVENT_PK: list(tracks)}
        self._space_pks = {TRACK_PK: list(space_pks)}

    def list_public_by_event(self, event_pk):
        return self._tracks[event_pk]

    def list_space_pks(self, track_pk):
        return self._space_pks[track_pk]


def _service(*, spaces, items, tracks=(), track_space_pks=(), track_items=()):
    return PrintMaterialsService(
        _Events(_event()),
        _Spaces(spaces),
        _AgendaItems(items, track_items),
        _Tracks(tracks, track_space_pks),
    )


def _timetable(service, **kwargs):
    return service.build_timetable(PrintQueryDTO(event_pk=1, tz=UTC, **kwargs))


class TestBuildTimetable:
    def test_tiles_sit_in_their_room_column_on_their_rows(self):
        hall = _space(9, "Hall", 0)
        spaces = [hall, _space(1, "Alfa", 0, parent_id=9), _space(2, "Bravo", 1)]
        items = [
            _item(1, 1, 9, 10, title="RPG", confirmed=True),
            _item(2, 2, 10, 11, title="Larp", confirmed=True),
            _item(3, 2, 9, 10, title="Hidden", confirmed=False),
        ]
        service = _service(spaces=spaces, items=items)

        document = _timetable(service, scope_name="Ground floor")

        assert document.scope_name == "Ground floor"
        assert document.is_unscoped is True
        page = document.pages[0]
        assert page.space_names == ["Alfa", "Bravo"]
        assert page.space_range_name == "Alfa - Bravo"
        assert [(r.start_time.hour, r.end_time.hour) for r in page.rows] == [
            (9, 10),
            (10, 11),
        ]
        assert [(t.session.title, t.col, t.row, t.span) for t in page.tiles] == [
            ("RPG", 1, 1, 1),
            ("Larp", 2, 2, 1),
        ]
        assert [row.minutes for row in page.rows] == [60, 60]

    def test_rows_measure_instants_across_the_autumn_fold(self):
        # 02:00 CEST and 02:00 CET are the same wall clock an hour apart; the
        # grid must draw that hour rather than fold it into nothing.
        tz = ZoneInfo("Europe/Warsaw")
        first = datetime(2026, 10, 25, 2, 0, tzinfo=tz, fold=0)
        second = datetime(2026, 10, 25, 2, 0, tzinfo=tz, fold=1)
        item = AgendaItemDTO(
            pk=1,
            schedule_confirmed=True,
            start_time=first,
            end_time=second,
            space_id=1,
            session_title="Night",
        )
        service = _service(spaces=[_space(1, "Alfa", 0)], items=[item])

        page = _timetable(service).pages[0]

        assert [row.minutes for row in page.rows] == [60]
        assert [(t.row, t.span) for t in page.tiles] == [(1, 1)]

    def test_a_long_session_spans_the_rows_a_short_one_cuts(self):
        spaces = [_space(1, "Alfa", 0), _space(2, "Bravo", 1)]
        items = [
            _item(1, 1, 10, 14, title="Long", confirmed=True),
            _item(2, 2, 10, 11, title="Short", confirmed=True),
        ]
        service = _service(spaces=spaces, items=items)

        page = _timetable(service).pages[0]

        assert [(r.start_time.hour, r.end_time.hour) for r in page.rows] == [
            (10, 11),
            (11, 14),
        ]
        assert [(t.session.title, t.row, t.span) for t in page.tiles] == [
            ("Long", 1, 2),
            ("Short", 1, 1),
        ]
        assert page.spans == [1, 2]

    def test_large_timetables_are_chunked_by_spaces(self):
        spaces = [_space(pk, f"Space {pk}", pk) for pk in range(1, 8)]
        items = [
            _item(1, 1, 9, 10, title="Opening", confirmed=True),
            _item(2, 7, 9, 10, title="Final table", confirmed=True),
        ]
        service = _service(spaces=spaces, items=items)

        document = _timetable(service)

        assert [page.space_names for page in document.pages] == [
            ["Space 1", "Space 2", "Space 3", "Space 4"],
            ["Space 5", "Space 6", "Space 7"],
        ]
        assert document.pages[0].space_range_name == "Space 1 - Space 4"
        assert document.pages[1].space_range_name == "Space 5 - Space 7"
        assert [(t.session.title, t.col) for t in document.pages[1].tiles] == [
            ("Final table", 3)
        ]

    def test_chunk_without_sessions_produces_no_page(self):
        spaces = [_space(pk, f"Space {pk}", pk) for pk in range(1, 8)]
        items = [_item(1, 7, 9, 10, title="Final table", confirmed=True)]
        service = _service(spaces=spaces, items=items)

        document = _timetable(service)

        assert [page.space_names for page in document.pages] == [
            ["Space 5", "Space 6", "Space 7"]
        ]

    def test_rows_are_chunk_local(self):
        # A session interval on another page chunk must not spawn an all-empty
        # row on this one.
        spaces = [_space(pk, f"Space {pk}", pk) for pk in range(1, 8)]
        items = [
            _item(1, 1, 9, 10, title="Opening", confirmed=True),
            _item(2, 7, 10, 12, title="Final table", confirmed=True),
        ]
        service = _service(spaces=spaces, items=items)

        document = _timetable(service)

        first, second = document.pages
        assert [(r.start_time.hour, r.end_time.hour) for r in first.rows] == [(9, 10)]
        assert [(r.start_time.hour, r.end_time.hour) for r in second.rows] == [(10, 12)]

    def test_a_day_at_the_row_cap_fits_one_sheet(self):
        items = [
            _item(hour, 1, hour, hour + 1, title=f"S{hour}", confirmed=True)
            for hour in range(MAX_TIMETABLE_ROWS_PER_PAGE)
        ]
        service = _service(spaces=[_space(1, "Alfa", 0)], items=items)

        document = _timetable(service)

        assert [
            (len(page.rows), page.sheet_index, page.sheet_count)
            for page in document.pages
        ] == [(MAX_TIMETABLE_ROWS_PER_PAGE, 1, 1)]

    def test_a_day_past_the_row_cap_continues_on_a_numbered_sheet(self):
        items = [
            _item(hour, 1, hour, hour + 1, title=f"S{hour}", confirmed=True)
            for hour in range(MAX_TIMETABLE_ROWS_PER_PAGE + 1)
        ]
        service = _service(spaces=[_space(1, "Alfa", 0)], items=items)

        first, second = _timetable(service).pages

        assert [(p.sheet_index, p.sheet_count) for p in (first, second)] == [
            (1, 2),
            (2, 2),
        ]
        assert (second.day, second.space_names) == (first.day, first.space_names)
        # Filled evenly, so neither sheet is a near-empty tail.
        assert abs(len(first.rows) - len(second.rows)) <= 1
        assert [t.session.title for t in first.tiles + second.tiles] == [
            f"S{hour}" for hour in range(MAX_TIMETABLE_ROWS_PER_PAGE + 1)
        ]
        assert (second.tiles[0].row, second.tiles[0].span) == (1, 1)

    def test_a_session_across_the_split_shows_on_both_sheets(self):
        cap = MAX_TIMETABLE_ROWS_PER_PAGE
        spaces = [_space(1, "Alfa", 0), _space(2, "Bravo", 1)]
        items = [
            _item(100, 1, 0, cap + 1, title="Marathon", confirmed=True),
            *(
                _item(hour, 2, hour, hour + 1, title=f"S{hour}", confirmed=True)
                for hour in range(cap + 1)
            ),
        ]
        service = _service(spaces=spaces, items=items)

        first, second = _timetable(service).pages

        marathon = [
            next(t for t in page.tiles if t.session.title == "Marathon")
            for page in (first, second)
        ]
        assert [(t.row, t.span) for t in marathon] == [
            (1, len(first.rows)),
            (1, len(second.rows)),
        ]
        # The tile is cut, its label is not: the reader sees the real hours.
        assert {(t.start_time.hour, t.end_time.hour) for t in marathon} == {
            (0, cap + 1)
        }

    def test_sheets_number_per_day_and_room_chunk(self):
        cap = MAX_TIMETABLE_ROWS_PER_PAGE
        spaces = [_space(pk, f"Space {pk}", pk) for pk in range(1, 6)]
        items = [
            *(
                _item(hour, 1, hour, hour + 1, title=f"S{hour}", confirmed=True)
                for hour in range(cap + 1)
            ),
            _item(100, 5, 9, 10, title="Lone", confirmed=True),
        ]
        service = _service(spaces=spaces, items=items)

        document = _timetable(service)

        assert [
            (page.space_range_name, page.sheet_index, page.sheet_count)
            for page in document.pages
        ] == [("Space 1 - Space 4", 1, 2), ("Space 1 - Space 4", 2, 2), (None, 1, 1)]

    def test_time_range_clips_sessions_and_completeness(self):
        spaces = [_space(1, "Alfa", 0)]
        items = [
            _item(1, 1, 9, 10, title="Morning", confirmed=True),
            _item(2, 1, 15, 16, title="Afternoon", confirmed=True),
        ]
        service = _service(spaces=spaces, items=items)

        document = _timetable(
            service,
            time_range=(
                datetime(2026, 6, 1, 8, 0, tzinfo=UTC),
                datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
            ),
        )

        titles = [t.session.title for page in document.pages for t in page.tiles]
        assert titles == ["Morning"]
        assert document.pages[0].space_range_name is None
        # A time-clipped print is a subset, never "the whole program".
        assert document.is_unscoped is False

    def test_a_track_lists_its_own_sessions_in_its_rooms(self):
        spaces = [_space(1, "Alfa", 0), _space(2, "Bravo", 1)]
        items = [_item(1, 1, 9, 10, title="RPG", confirmed=True)]
        track_items = [
            _item(2, 2, 10, 11, title="Larp", confirmed=True),
            _item(3, 2, 11, 12, title="Hidden", confirmed=False),
        ]
        service = _service(
            spaces=spaces, items=items, track_items=track_items, track_space_pks=[2]
        )

        document = _timetable(service, track_pk=TRACK_PK)

        assert document.is_unscoped is False
        assert [page.space_names for page in document.pages] == [["Bravo"]]
        assert [t.session.title for t in document.pages[0].tiles] == ["Larp"]

    def test_days_follow_the_query_time_zone(self):
        spaces = [_space(1, "Alfa", 0)]
        items = [_item(1, 1, 12, 13, title="Noon", confirmed=True)]
        service = _service(spaces=spaces, items=items)

        document = service.build_timetable(
            PrintQueryDTO(event_pk=EVENT_PK, tz=ZoneInfo("Pacific/Kiritimati"))
        )

        assert [page.day for page in document.pages] == [date(2026, 6, 2)]

    def test_scoped_to_a_space_subtree(self):
        spaces = [_space(1, "Alfa", 0)]
        items = [_item(1, 1, 9, 10, title="RPG", confirmed=True)]
        service = _service(spaces=spaces, items=items)

        document = _timetable(service, scope_space_pks=frozenset({1}))

        assert document.is_unscoped is False

    def test_session_outside_scope_adds_no_row(self):
        # The session lives in Cesarz, outside the scoped space set — it must
        # not spawn a row (nor a page) in the scoped grid.
        spaces = [_space(1, "Alfa", 0), _space(3, "Cesarz", 2)]
        items = [_item(1, 3, 12, 13, title="Out of scope", confirmed=True)]
        service = _service(spaces=spaces, items=items)

        document = _timetable(service, scope_space_pks=frozenset({1}))

        assert document.pages == []


def _session_list(service, **kwargs):
    return service.build_session_list(PrintQueryDTO(event_pk=1, tz=UTC, **kwargs))


class TestBuildSessionList:
    def test_whole_event_in_time_then_programme_room_order(self):
        spaces = [_space(1, "Alfa", 1), _space(2, "Bravo", 0)]
        spaces[0].programme_order = 0
        spaces[1].programme_order = 1
        items = [
            _item(1, 2, 9, 10, title="Late room", confirmed=True, space_name="Bravo"),
            _item(2, 1, 9, 10, title="Early room", confirmed=True, space_name="Alfa"),
            _item(3, 1, 11, 12, title="Second day", confirmed=True, day=2),
            _item(
                4,
                1,
                8,
                9,
                title="First",
                confirmed=True,
                description="Tale",
                space_name="Alfa",
            ),
            _item(5, 1, 7, 8, title="Hidden", confirmed=False),
        ]
        service = _service(spaces=spaces, items=items)

        document = _session_list(service)

        assert [(p.day.day, [s.title for s in p.sessions]) for p in document.pages] == [
            (1, ["First", "Early room", "Late room"]),
            (2, ["Second day"]),
        ]
        first = document.pages[0].sessions[0]
        assert (first.description, first.space_name) == ("Tale", "Alfa")

    def test_days_follow_the_query_time_zone(self):
        items = [_item(1, 1, 12, 13, title="Noon", confirmed=True)]
        service = _service(spaces=[_space(1, "Alfa", 0)], items=items)

        document = service.build_session_list(
            PrintQueryDTO(event_pk=1, tz=ZoneInfo("Pacific/Kiritimati"))
        )

        assert [page.day for page in document.pages] == [date(2026, 6, 2)]

    def test_a_day_at_the_row_cap_fits_one_sheet(self):
        items = [
            _item(hour, 1, hour, hour + 1, title=f"S{hour}", confirmed=True)
            for hour in range(MAX_SESSION_LIST_ROWS_PER_SHEET)
        ]
        service = _service(spaces=[_space(1, "Alfa", 0)], items=items)

        document = _session_list(service)

        assert [
            (len(page.sessions), page.sheet_index, page.sheet_count)
            for page in document.pages
        ] == [(MAX_SESSION_LIST_ROWS_PER_SHEET, 1, 1)]

    def test_a_busy_day_continues_on_a_numbered_sheet(self):
        cap = MAX_SESSION_LIST_ROWS_PER_SHEET
        items = [
            _item(hour, 1, hour, hour + 1, title=f"S{hour}", confirmed=True)
            for hour in range(cap + 1)
        ]
        service = _service(spaces=[_space(1, "Alfa", 0)], items=items)

        document = _session_list(service)

        assert [
            (page.day.day, page.sheet_index, page.sheet_count)
            for page in document.pages
        ] == [(1, 1, 2), (1, 2, 2)]
        first, second = (len(page.sessions) for page in document.pages)
        assert (first + second, abs(first - second) <= 1) == (cap + 1, True)

    def test_descriptions_lower_the_row_cap(self):
        cap = MAX_SESSION_LIST_DESCRIBED_ROWS_PER_SHEET
        items = [
            _item(hour, 1, hour, hour + 1, title=f"S{hour}", confirmed=True)
            for hour in range(cap + 1)
        ]
        service = _service(spaces=[_space(1, "Alfa", 0)], items=items)

        bare = _session_list(service)
        described = _session_list(service, descriptions=True)

        assert [len(bare.pages), len(described.pages)] == [1, 2]
        assert max(len(page.sessions) for page in described.pages) <= cap

    def test_a_room_outside_the_programme_sorts_last_within_its_hour(self):
        spaces = [_space(1, "Alfa", 1), _space(2, "Bravo", 0)]
        items = [
            _item(1, 7, 9, 10, title="Lobby", confirmed=True, space_name="Lobby"),
            _item(2, 1, 9, 10, title="Alfa", confirmed=True, space_name="Alfa"),
            _item(3, 2, 9, 10, title="Bravo", confirmed=True, space_name="Bravo"),
        ]
        service = _service(spaces=spaces, items=items)

        document = _session_list(service)

        assert [s.title for s in document.pages[0].sessions] == [
            "Bravo",
            "Alfa",
            "Lobby",
        ]


class TestBuildAreaSchedule:
    def test_no_range_does_not_clip_sessions_to_event_bounds(self):
        spaces = [_space(1, "Alfa", 0)]
        items = [
            _item(1, 1, 10, 11, title="Beyond declared end", confirmed=True, day=2),
            _item(2, 1, 12, 13, title="Hidden", confirmed=False, day=2),
        ]
        service = _service(spaces=spaces, items=items)

        document = service.build_area_schedule(PrintQueryDTO(event_pk=1, tz=UTC))

        assert [s.title for s in document.spaces[0].sessions] == ["Beyond declared end"]
        assert document.range_start == _event().start_time
        assert document.range_end == items[0].end_time

    def test_scoped_rooms_keep_their_name_and_capacity(self):
        spaces = [_space(1, "Alfa", 0), _space(2, "Bravo", 1)]
        service = _service(spaces=spaces, items=[])

        document = service.build_area_schedule(
            PrintQueryDTO(
                event_pk=1, tz=UTC, scope_space_pks=frozenset({2}), scope_name="Wing"
            )
        )

        assert document.scope_name == "Wing"
        assert [(s.space_name, s.capacity) for s in document.spaces] == [("Bravo", 20)]

    def test_a_time_range_frames_the_page_and_clips_sessions(self):
        spaces = [_space(1, "Alfa", 0), _space(2, "Bravo", 1)]
        items = [
            _item(1, 1, 9, 10, title="Morning", confirmed=True),
            _item(2, 1, 15, 16, title="Afternoon", confirmed=True),
        ]
        service = _service(spaces=spaces, items=items)
        time_range = (
            datetime(2026, 6, 1, 8, 0, tzinfo=UTC),
            datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
        )

        document = service.build_area_schedule(
            PrintQueryDTO(event_pk=1, tz=UTC, time_range=time_range)
        )

        assert (document.range_start, document.range_end) == time_range
        assert [[s.title for s in space.sessions] for space in document.spaces] == [
            ["Morning"],
            [],
        ]

    def test_a_track_narrows_rooms_to_the_ones_it_uses(self):
        spaces = [_space(1, "Alfa", 0), _space(2, "Bravo", 1)]
        items = [_item(1, 1, 9, 10, title="RPG", confirmed=True)]
        track_items = [
            _item(2, 1, 10, 11, title="Larp", confirmed=True),
            _item(3, 1, 11, 12, title="Hidden", confirmed=False),
        ]
        service = _service(
            spaces=spaces, items=items, track_items=track_items, track_space_pks=[1]
        )

        document = service.build_area_schedule(
            PrintQueryDTO(event_pk=1, tz=UTC, track_pk=TRACK_PK)
        )

        assert [space.space_name for space in document.spaces] == ["Alfa"]
        assert [s.title for s in document.spaces[0].sessions] == ["Larp"]


class TestBuildDoorCards:
    def test_one_card_per_room_and_day_with_sessions_in_time_order(self):
        hall = _space(9, "Hall", 0)
        spaces = [hall, _space(1, "Alfa", 0, parent_id=9), _space(2, "Bravo", 1)]
        items = [
            _item(1, 1, 11, 12, title="Late", confirmed=True),
            _item(2, 1, 9, 10, title="Early", confirmed=True),
            _item(3, 1, 9, 10, title="Next day", confirmed=True, day=2),
            _item(4, 1, 13, 14, title="Hidden", confirmed=False),
        ]
        service = _service(spaces=spaces, items=items)

        document = service.build_door_cards(
            PrintQueryDTO(event_pk=1, tz=UTC, scope_name="Ground floor")
        )

        assert document.scope_name == "Ground floor"
        assert [
            (card.space_name, card.day.day, [e.session.title for e in card.entries])
            for card in document.cards
        ] == [("Alfa", 1, ["Early", "Late"]), ("Alfa", 2, ["Next day"])]
        assert [card.capacity for card in document.cards] == [20, 20]

    def test_scope_and_track_narrow_the_rooms(self):
        spaces = [_space(1, "Alfa", 0), _space(2, "Bravo", 1), _space(3, "Cesarz", 2)]
        items = [
            _item(1, 1, 9, 10, title="A", confirmed=True),
            _item(2, 2, 9, 10, title="B", confirmed=True),
            _item(3, 3, 9, 10, title="C", confirmed=True),
        ]
        service = _service(spaces=spaces, items=items, track_space_pks=[2, 3])

        document = service.build_door_cards(
            PrintQueryDTO(
                event_pk=1, tz=UTC, scope_space_pks=frozenset({1, 2}), track_pk=TRACK_PK
            )
        )

        assert [card.space_name for card in document.cards] == ["Bravo"]

    def test_days_follow_the_query_time_zone(self):
        spaces = [_space(1, "Alfa", 0)]
        items = [_item(1, 1, 12, 13, title="Noon", confirmed=True)]
        service = _service(spaces=spaces, items=items)

        document = service.build_door_cards(
            PrintQueryDTO(event_pk=1, tz=ZoneInfo("Pacific/Kiritimati"))
        )

        assert [card.day for card in document.cards] == [date(2026, 6, 2)]

    def test_a_time_range_drops_sessions_outside_it(self):
        spaces = [_space(1, "Alfa", 0)]
        items = [
            _item(1, 1, 9, 10, title="Morning", confirmed=True),
            _item(2, 1, 15, 16, title="Afternoon", confirmed=True),
            _item(3, 1, 13, 14, title="Ends at range start", confirmed=True),
            _item(4, 1, 18, 19, title="Starts at range end", confirmed=True),
        ]
        service = _service(spaces=spaces, items=items)

        document = service.build_door_cards(
            PrintQueryDTO(
                event_pk=1,
                tz=UTC,
                time_range=(
                    datetime(2026, 6, 1, 14, 0, tzinfo=UTC),
                    datetime(2026, 6, 1, 18, 0, tzinfo=UTC),
                ),
            )
        )

        assert [[e.session.title for e in card.entries] for card in document.cards] == [
            ["Afternoon"]
        ]

    def test_a_day_at_the_entry_cap_fits_one_card(self):
        items = [
            _item(hour, 1, hour, hour + 1, title=f"S{hour}", confirmed=True)
            for hour in range(MAX_DOOR_CARD_ENTRIES_PER_SHEET)
        ]
        service = _service(spaces=[_space(1, "Alfa", 0)], items=items)

        document = service.build_door_cards(PrintQueryDTO(event_pk=1, tz=UTC))

        assert [
            (len(card.entries), card.sheet_index, card.sheet_count)
            for card in document.cards
        ] == [(MAX_DOOR_CARD_ENTRIES_PER_SHEET, 1, 1)]

    def test_a_busy_day_continues_on_a_numbered_card(self):
        items = [
            _item(hour, 1, hour, hour + 1, title=f"S{hour}", confirmed=True)
            for hour in range(MAX_DOOR_CARD_ENTRIES_PER_SHEET + 1)
        ]
        items.append(_item(100, 1, 9, 10, title="Next day", confirmed=True, day=2))
        service = _service(spaces=[_space(1, "Alfa", 0)], items=items)

        document = service.build_door_cards(PrintQueryDTO(event_pk=1, tz=UTC))

        assert [
            (card.space_name, card.day.day, card.sheet_index, card.sheet_count)
            for card in document.cards
        ] == [("Alfa", 1, 1, 2), ("Alfa", 1, 2, 2), ("Alfa", 2, 1, 1)]
        first, second = document.cards[:2]
        assert abs(len(first.entries) - len(second.entries)) <= 1
        assert [e.session.title for e in first.entries + second.entries] == [
            f"S{hour}" for hour in range(MAX_DOOR_CARD_ENTRIES_PER_SHEET + 1)
        ]


class TestListTracks:
    def test_public_tracks_become_print_options(self):
        service = _service(
            spaces=[],
            items=[],
            tracks=[TrackDTO.model_construct(pk=5, name="Larp", slug="larp")],
        )

        assert service.list_tracks(1) == [
            PrintOptionDTO(pk=5, name="Larp", slug="larp")
        ]


class _Reminders:
    def __init__(self, due):
        self._due = due
        self.printed = []
        self.sent = []
        self.queries = []

    def list_pending_reminders(self, *, now, lead_time):
        self.queries.append((now, lead_time))
        return list(self._due)

    def mark_printed(self, event_pk):
        self.printed.append(event_pk)

    def mark_reminder_sent(self, event_pk, *, at):
        self.sent.append((event_pk, at))


class _Notifier:
    def __init__(self):
        self.notifications = []

    def notify_printables_ready(self, notification):
        self.notifications.append(notification)


class _Transaction:
    @staticmethod
    def atomic():
        return nullcontext()


class TestPrintablesReminderService:
    def test_marks_each_event_sent_and_notifies_every_recipient(self):
        now = datetime(2026, 5, 30, 9, 0, tzinfo=UTC)
        due = [
            PrintablesReminderDTO(
                event_pk=1,
                event_name="Konwent",
                event_slug="konwent",
                sphere_domain="k.example",
                recipients=[1, 2],
            ),
            PrintablesReminderDTO(
                event_pk=2,
                event_name="Sesja",
                event_slug="sesja",
                sphere_domain="z.example",
                recipients=[],
            ),
        ]
        reminders = _Reminders(due)
        notifier = _Notifier()
        service = PrintablesReminderService(
            transaction=_Transaction(), reminders=reminders, notifier=notifier
        )

        sent = service.send_due_reminders(now=now)

        assert sent == len(due)
        assert reminders.queries == [(now, PRINTABLES_REMINDER_LEAD_TIME)]
        assert reminders.sent == [(1, now), (2, now)]
        assert [
            (n.recipient_user_id, n.event_slug) for n in notifier.notifications
        ] == [(1, "konwent"), (2, "konwent")]

    def test_mark_printed_records_the_event(self):
        reminders = _Reminders([])
        service = PrintablesReminderService(
            transaction=_Transaction(), reminders=reminders, notifier=_Notifier()
        )

        service.mark_printed(7)

        assert reminders.printed == [7]
