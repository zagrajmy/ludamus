from contextlib import nullcontext
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from ludamus.mills.printing import PrintablesReminderService, PrintMaterialsService
from ludamus.pacts import AgendaItemDTO, EventDTO, SpaceDTO, TrackDTO
from ludamus.pacts.printing import (
    PrintablesReminderDTO,
    PrintablesReminderRecipientDTO,
    PrintOptionDTO,
    PrintQueryDTO,
)


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

    def list_by_event(self, _event_pk, *, public_only=False):
        return list(self._rows)

    def list_by_track(self, _track_pk, *, public_only=False):
        return list(self._rows)


class _Tracks:
    def __init__(self, tracks=(), space_pks=()):
        self._tracks = list(tracks)
        self._space_pks = list(space_pks)

    def list_public_by_event(self, _event_pk):
        return self._tracks

    def list_space_pks(self, _track_pk):
        return self._space_pks


def _service(*, spaces, items, tracks=(), track_space_pks=()):
    return PrintMaterialsService(
        _Events(_event()),
        _ListByEvent(spaces),
        _ListByEvent(items),
        _Tracks(tracks, track_space_pks),
    )


def _timetable(service, **kwargs):
    return service.build_timetable(PrintQueryDTO(event_pk=1, tz=UTC, **kwargs))


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
        assert document.is_unscoped is False

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


class TestBuildAreaSchedule:
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
        service = _service(spaces=spaces, items=items, track_space_pks=[1])

        document = service.build_area_schedule(
            PrintQueryDTO(event_pk=1, tz=UTC, track_pk=5)
        )

        assert [space.space_name for space in document.spaces] == ["Alfa"]


class TestBuildDoorCards:
    def test_one_card_per_room_and_day_with_sessions_in_time_order(self):
        hall = _space(9, "Hall", 0)
        spaces = [hall, _space(1, "Alfa", 0, parent_id=9), _space(2, "Bravo", 1)]
        items = [
            _item(1, 1, 11, 12, title="Late", confirmed=True),
            _item(2, 1, 9, 10, title="Early", confirmed=True),
            _item(3, 1, 9, 10, title="Next day", confirmed=True, day=2),
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

    def test_a_time_range_drops_sessions_outside_it(self):
        spaces = [_space(1, "Alfa", 0)]
        items = [
            _item(1, 1, 9, 10, title="Morning", confirmed=True),
            _item(2, 1, 15, 16, title="Afternoon", confirmed=True),
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

    def list_pending_reminders(self, *, now, lead_time):
        del now, lead_time
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
                recipients=[
                    PrintablesReminderRecipientDTO(user_id=1, email="a@k.example"),
                    PrintablesReminderRecipientDTO(user_id=2, email="b@k.example"),
                ],
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
        assert reminders.sent == [(1, now), (2, now)]
        assert [(n.recipient_email, n.event_slug) for n in notifier.notifications] == [
            ("a@k.example", "konwent"),
            ("b@k.example", "konwent"),
        ]

    def test_mark_printed_records_the_event(self):
        reminders = _Reminders([])
        service = PrintablesReminderService(
            transaction=_Transaction(), reminders=reminders, notifier=_Notifier()
        )

        service.mark_printed(7)

        assert reminders.printed == [7]
