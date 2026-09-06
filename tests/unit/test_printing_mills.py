from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from ludamus.mills.printing import PrintMaterialsService
from ludamus.pacts import AgendaItemDTO, EventDTO, SpaceDTO
from ludamus.pacts.printing import PrintQueryDTO


def _event():
    return EventDTO(
        description="Konwent dla nerdów",
        end_time=datetime(2026, 6, 1, 18, 0, tzinfo=UTC),
        name="Konwent",
        pk=1,
        proposal_end_time=None,
        proposal_start_time=None,
        publication_time=None,
        slug="konwent",
        sphere_id=1,
        start_time=datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
    )


def _space(pk, name, order, area_id=None):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return SpaceDTO(
        area_id=area_id,
        capacity=20,
        creation_time=now,
        modification_time=now,
        name=name,
        order=order,
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
        session_confirmed=confirmed,
        start_time=datetime(2026, 6, day, start_hour, 0, tzinfo=UTC),
        end_time=datetime(2026, 6, day, end_hour, 0, tzinfo=UTC),
        space_id=space_id,
        space_name=space_name,
        session_title=title,
        session_description=description,
        presenter_name="GM",
    )


class _Events:
    def __init__(self, event):
        self._event = event

    def read(self, _pk):
        return self._event


class _ListByEvent:
    def __init__(self, rows):
        self._rows = rows

    def list_by_event(self, _event_pk):
        return list(self._rows)

    def list_by_track(self, _track_pk):
        return list(self._rows)


class _Tracks:
    def __init__(self, space_pks=()):
        self._space_pks = list(space_pks)

    def list_public_by_event(self, _event_pk):
        return []

    def list_space_pks(self, _track_pk):
        return list(self._space_pks)


def _service(*, spaces, items, tracks=None):
    return PrintMaterialsService(
        _Events(_event()),
        _ListByEvent(spaces),
        _ListByEvent(items),
        tracks or _Tracks(),
    )


def _door_cards(service, **kwargs):
    return service.build_door_cards(PrintQueryDTO(event_pk=1, tz=UTC, **kwargs))


def _timetable(service, **kwargs):
    return service.build_timetable(PrintQueryDTO(event_pk=1, tz=UTC, **kwargs))


def _area_schedule(service, window, **kwargs):
    return service.build_area_schedule(
        PrintQueryDTO(event_pk=1, tz=UTC, time_range=window, **kwargs)
    )


class TestBuildDoorCards:
    def test_one_card_per_space_in_order(self):
        spaces = [_space(2, "Bravo", 1), _space(1, "Alfa", 0)]
        items = [
            _item(1, 1, 9, 10, title="RPG", confirmed=True),
            _item(2, 2, 9, 10, title="Larp", confirmed=True),
        ]
        service = _service(spaces=spaces, items=items)

        document = _door_cards(service)

        assert [c.space_name for c in document.cards] == ["Alfa", "Bravo"]

    def test_a_room_used_on_two_days_gets_a_card_per_day(self):
        spaces = [_space(1, "Alfa", 0)]
        items = [
            _item(1, 1, 9, 10, title="RPG", confirmed=True, day=2),
            _item(2, 1, 14, 15, title="Wieczorny", confirmed=True, day=1),
            _item(3, 1, 9, 10, title="Larp", confirmed=True, day=1),
        ]
        service = _service(spaces=spaces, items=items)

        document = _door_cards(service)

        assert [(c.space_name, c.day) for c in document.cards] == [
            ("Alfa", date(2026, 6, 1)),
            ("Alfa", date(2026, 6, 2)),
        ]
        assert [[e.session.title for e in c.entries] for c in document.cards] == [
            ["Larp", "Wieczorny"],
            ["RPG"],
        ]

    def test_time_range_keeps_overlapping_entries_and_drops_empty_rooms(self):
        spaces = [_space(1, "Alfa", 0), _space(2, "Bravo", 1)]
        items = [
            _item(1, 1, 9, 10, title="RPG", confirmed=True),
            _item(2, 2, 14, 15, title="Larp", confirmed=True),
        ]
        service = _service(spaces=spaces, items=items)

        document = _door_cards(
            service,
            time_range=(
                datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
                datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
            ),
        )

        assert [c.space_name for c in document.cards] == ["Alfa"]
        entries = document.cards[0].entries
        assert [entry.session.title for entry in entries] == ["RPG"]

    def test_empty_slots_and_sessionless_spaces_are_omitted(self):
        # Cards are participant-facing: no "free slot" rows, no card at all for
        # a room with nothing scheduled.
        spaces = [_space(1, "Alfa", 0), _space(2, "Bravo", 1)]
        items = [_item(1, 1, 9, 10, title="RPG", confirmed=True)]
        service = _service(spaces=spaces, items=items)

        document = _door_cards(service)

        assert [c.space_name for c in document.cards] == ["Alfa"]
        entries = document.cards[0].entries
        assert [e.session.title for e in entries] == ["RPG"]

    def test_includes_unconfirmed_scheduled_session(self):
        spaces = [_space(1, "Alfa", 0)]
        items = [_item(1, 1, 9, 10, title="Larp", confirmed=False)]
        service = _service(spaces=spaces, items=items)

        # The manager toggle: only an explicit opt-in prints pending sessions.
        document = _door_cards(service, confirmed_only=False)

        entries = document.cards[0].entries
        assert entries[0].session is not None
        assert entries[0].session.title == "Larp"


class TestBuildTimetable:
    def test_tiles_sit_in_their_room_column_on_their_rows(self):
        spaces = [_space(1, "Alfa", 0), _space(2, "Bravo", 1)]
        items = [
            _item(1, 1, 9, 10, title="RPG", confirmed=True),
            _item(2, 2, 10, 11, title="Larp", confirmed=True),
        ]
        service = _service(spaces=spaces, items=items)

        document = _timetable(service)

        page = document.pages[0]
        assert page.space_names == ["Alfa", "Bravo"]
        assert [(r.start_time.hour, r.end_time.hour) for r in page.rows] == [
            (9, 10),
            (10, 11),
        ]
        assert [(t.session.title, t.col, t.row, t.span) for t in page.tiles] == [
            ("RPG", 1, 1, 1),
            ("Larp", 2, 2, 1),
        ]
        assert [row.minutes for row in page.rows] == [60, 60]

    def test_rows_come_from_session_times(self):
        # Time slots are proposer availability windows, not display units; the
        # grid rows come from the sessions' real times.
        spaces = [_space(1, "Alfa", 0)]
        items = [_item(1, 1, 10, 11, title="RPG", confirmed=True)]
        service = _service(spaces=spaces, items=items)

        document = _timetable(service)

        rows = document.pages[0].rows
        assert [(r.start_time, r.end_time) for r in rows] == [
            (
                datetime(2026, 6, 1, 10, 0, tzinfo=UTC),
                datetime(2026, 6, 1, 11, 0, tzinfo=UTC),
            )
        ]

    def test_rows_measure_instants_across_the_autumn_fold(self):
        # 02:00 CEST and 02:00 CET are the same wall clock an hour apart; the
        # grid must draw that hour rather than fold it into nothing.
        tz = ZoneInfo("Europe/Warsaw")
        first = datetime(2026, 10, 25, 2, 0, tzinfo=tz, fold=0)
        second = datetime(2026, 10, 25, 2, 0, tzinfo=tz, fold=1)
        item = AgendaItemDTO(
            pk=1,
            session_confirmed=True,
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

    def test_a_lone_session_makes_one_tile(self):
        spaces = [_space(1, "Alfa", 0)]
        items = [_item(1, 1, 10, 11, title="Solo", confirmed=True)]
        service = _service(spaces=spaces, items=items)

        document = _timetable(service)

        titles = [t.session.title for page in document.pages for t in page.tiles]
        assert titles == ["Solo"]

    def test_one_page_per_date_with_sessions(self):
        spaces = [_space(1, "Alfa", 0)]
        items = [
            _item(1, 1, 9, 10, title="Day one", confirmed=True),
            _item(2, 1, 9, 10, title="Day two", confirmed=True, day=2),
        ]
        service = _service(spaces=spaces, items=items)

        document = _timetable(service)

        assert [d.day for d in document.pages] == [date(2026, 6, 1), date(2026, 6, 2)]

    def test_nothing_scheduled_produces_no_pages(self):
        spaces = [_space(1, "Alfa", 0)]
        service = _service(spaces=spaces, items=[])

        document = _timetable(service)

        assert document.pages == []

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
        # A time-clipped print is a subset, never "the whole program".
        assert document.is_complete is False

    def test_documents_carry_event_description(self):
        service = _service(spaces=[_space(1, "Alfa", 0)], items=[])

        assert _timetable(service).event_description == "Konwent dla nerdów"
        assert _door_cards(service).event_description == "Konwent dla nerdów"


class TestConfirmedOnly:
    def test_timetable_drops_unconfirmed_when_confirmed_only(self):
        spaces = [_space(1, "Alfa", 0)]
        items = [
            _item(1, 1, 9, 10, title="Confirmed", confirmed=True),
            _item(2, 1, 10, 11, title="Pending", confirmed=False),
        ]
        service = _service(spaces=spaces, items=items)

        document = _timetable(service, confirmed_only=True)

        titles = [t.session.title for page in document.pages for t in page.tiles]
        assert titles == ["Confirmed"]

    def test_door_cards_drop_unconfirmed_when_confirmed_only(self):
        spaces = [_space(1, "Alfa", 0)]
        items = [_item(1, 1, 9, 10, title="Pending", confirmed=False)]
        service = _service(spaces=spaces, items=items)

        document = _door_cards(service, confirmed_only=True)

        assert document.cards == []


class TestTimetableCompleteness:
    def test_complete_when_every_scheduled_session_confirmed(self):
        spaces = [_space(1, "Alfa", 0)]
        items = [_item(1, 1, 9, 10, title="RPG", confirmed=True)]
        service = _service(spaces=spaces, items=items)

        assert _timetable(service).is_complete is True

    def test_incomplete_when_a_scheduled_session_is_unconfirmed(self):
        spaces = [_space(1, "Alfa", 0)]
        items = [
            _item(1, 1, 9, 10, title="RPG", confirmed=True),
            _item(2, 1, 10, 11, title="Maybe", confirmed=False),
        ]
        service = _service(spaces=spaces, items=items)

        # Completeness reflects the whole program, even when the public view is
        # confirmed-only — a pending session means the paper is partial.
        assert _timetable(service, confirmed_only=True).is_complete is False

    def test_incomplete_when_nothing_scheduled(self):
        spaces = [_space(1, "Alfa", 0)]
        service = _service(spaces=spaces, items=[])

        assert _timetable(service).is_complete is False

    def test_scoped_timetable_is_never_complete(self):
        # A scoped print (one venue/area) is a subset, so never "the whole thing".
        spaces = [_space(1, "Alfa", 0)]
        items = [_item(1, 1, 9, 10, title="RPG", confirmed=True)]
        service = _service(spaces=spaces, items=items)

        document = _timetable(service, scope_space_pks=frozenset({1}))

        assert document.is_complete is False


def _session_list(service, **kwargs):
    return service.build_session_list(PrintQueryDTO(event_pk=1, tz=UTC, **kwargs))


class TestBuildSessionList:
    def test_whole_event_in_time_then_room_order(self):
        spaces = [_space(1, "Alfa", 0), _space(2, "Bravo", 1)]
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
        ]
        service = _service(spaces=spaces, items=items)

        document = _session_list(service)

        assert [s.title for s in document.sessions] == [
            "First",
            "Early room",
            "Late room",
            "Second day",
        ]
        assert document.sessions[0].description == "Tale"
        assert document.sessions[0].space_name == "Alfa"

    def test_drops_unconfirmed_when_confirmed_only(self):
        spaces = [_space(1, "Alfa", 0)]
        items = [
            _item(1, 1, 9, 10, title="Sure", confirmed=True),
            _item(2, 1, 10, 11, title="Maybe", confirmed=False),
        ]
        service = _service(spaces=spaces, items=items)

        assert [s.title for s in _session_list(service).sessions] == ["Sure"]
        assert [
            s.title for s in _session_list(service, confirmed_only=False).sessions
        ] == ["Sure", "Maybe"]

    def test_nothing_scheduled_means_no_sessions(self):
        service = _service(spaces=[_space(1, "Alfa", 0)], items=[])

        assert _session_list(service).sessions == []


class TestBuildAreaSchedule:
    def test_sessions_within_range_carry_full_description(self):
        spaces = [_space(1, "Alfa", 0)]
        items = [
            _item(1, 1, 10, 11, title="RPG", confirmed=True, description="A long tale")
        ]
        service = _service(spaces=spaces, items=items)
        window = (
            datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
            datetime(2026, 6, 1, 15, 0, tzinfo=UTC),
        )

        document = _area_schedule(service, window)

        space = document.spaces[0]
        assert space.space_name == "Alfa"
        assert [s.title for s in space.sessions] == ["RPG"]
        assert space.sessions[0].description == "A long tale"

    def test_sessions_outside_range_are_excluded(self):
        spaces = [_space(1, "Alfa", 0)]
        items = [_item(1, 1, 20, 21, title="Late night", confirmed=True)]
        service = _service(spaces=spaces, items=items)
        window = (
            datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
            datetime(2026, 6, 1, 15, 0, tzinfo=UTC),
        )

        document = _area_schedule(service, window)

        assert document.spaces[0].sessions == []

    def test_confirmed_only_excludes_pending_sessions(self):
        spaces = [_space(1, "Alfa", 0)]
        items = [_item(1, 1, 10, 11, title="Pending", confirmed=False)]
        service = _service(spaces=spaces, items=items)
        window = (
            datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
            datetime(2026, 6, 1, 15, 0, tzinfo=UTC),
        )

        document = _area_schedule(service, window, confirmed_only=True)

        assert document.spaces[0].sessions == []

    def test_no_range_defaults_to_event_bounds(self):
        spaces = [_space(1, "Alfa", 0)]
        items = [_item(1, 1, 10, 11, title="RPG", confirmed=True)]
        service = _service(spaces=spaces, items=items)

        document = service.build_area_schedule(PrintQueryDTO(event_pk=1, tz=UTC))

        assert document.range_start == _event().start_time
        assert document.range_end == _event().end_time
        assert [s.title for s in document.spaces[0].sessions] == ["RPG"]

    def test_no_range_does_not_clip_sessions_to_event_bounds(self):
        spaces = [_space(1, "Alfa", 0)]
        items = [
            _item(1, 1, 10, 11, title="Beyond declared end", confirmed=True, day=2)
        ]
        service = _service(spaces=spaces, items=items)

        document = service.build_area_schedule(PrintQueryDTO(event_pk=1, tz=UTC))

        assert [s.title for s in document.spaces[0].sessions] == ["Beyond declared end"]
        assert document.range_start == _event().start_time
        assert document.range_end == items[0].end_time

    def test_track_scopes_spaces(self):
        spaces = [_space(1, "Alfa", 0), _space(2, "Bravo", 1)]
        items = [_item(1, 1, 10, 11, title="Tracked", confirmed=True)]
        service = _service(spaces=spaces, items=items, tracks=_Tracks(space_pks=[1]))
        window = (
            datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
            datetime(2026, 6, 1, 15, 0, tzinfo=UTC),
        )

        document = _area_schedule(service, window, track_pk=7)

        assert [s.space_name for s in document.spaces] == ["Alfa"]
        assert [s.title for s in document.spaces[0].sessions] == ["Tracked"]

    def test_carries_range_bounds(self):
        spaces = [_space(1, "Alfa", 0)]
        service = _service(spaces=spaces, items=[])
        window = (
            datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
            datetime(2026, 6, 1, 15, 0, tzinfo=UTC),
        )

        document = _area_schedule(service, window)

        assert document.range_start == window[0]
        assert document.range_end == window[1]


class TestScoping:
    @staticmethod
    def _scoped_service():
        spaces = [_space(1, "Alfa", 0), _space(2, "Bravo", 1), _space(3, "Cesarz", 2)]
        items = [_item(1, 1, 9, 10, title="RPG", confirmed=True)]
        return _service(spaces=spaces, items=items)

    def test_timetable_filtered_to_scope_space_pks(self):
        document = _timetable(
            self._scoped_service(),
            scope_space_pks=frozenset({1, 2}),
            scope_name="Budynek A",
        )

        assert document.pages[0].space_names == ["Alfa", "Bravo"]
        assert document.scope_name == "Budynek A"

    def test_door_cards_filtered_to_single_space(self):
        spaces = [_space(1, "Alfa", 0), _space(2, "Bravo", 1)]
        items = [
            _item(1, 1, 9, 10, title="RPG", confirmed=True),
            _item(2, 2, 9, 10, title="Larp", confirmed=True),
        ]
        service = _service(spaces=spaces, items=items)

        document = _door_cards(
            service, scope_space_pks=frozenset({1}), scope_name="Parter"
        )

        assert [c.space_name for c in document.cards] == ["Alfa"]
        assert document.scope_name == "Parter"

    def test_unscoped_has_no_scope_name(self):
        document = _timetable(self._scoped_service())

        assert document.scope_name is None
        assert document.pages[0].space_names == ["Alfa", "Bravo", "Cesarz"]

    def test_session_outside_scope_adds_no_row(self):
        # The session lives in Cesarz, outside the scoped space set — it must
        # not spawn a row (nor a page) in the scoped grid.
        spaces = [_space(1, "Alfa", 0), _space(3, "Cesarz", 2)]
        items = [_item(1, 3, 12, 13, title="Out of scope", confirmed=True)]
        service = _service(spaces=spaces, items=items)

        document = _timetable(service, scope_space_pks=frozenset({1}))

        assert document.pages == []
