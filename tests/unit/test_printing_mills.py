from datetime import UTC, date, datetime

from ludamus.mills.printing import PrintMaterialsService
from ludamus.pacts import AgendaItemDTO, EventDTO, SpaceDTO, TimeSlotDTO


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


def _slot(pk, start_hour, end_hour):
    return _slot_on_day(pk, 1, start_hour, end_hour)


def _slot_on_day(pk, day, start_hour, end_hour):
    return TimeSlotDTO(
        pk=pk,
        start_time=datetime(2026, 6, day, start_hour, 0, tzinfo=UTC),
        end_time=datetime(2026, 6, day, end_hour, 0, tzinfo=UTC),
    )


def _item(pk, space_id, start_hour, end_hour, *, title, confirmed, description=""):
    return AgendaItemDTO(
        pk=pk,
        session_confirmed=confirmed,
        start_time=datetime(2026, 6, 1, start_hour, 0, tzinfo=UTC),
        end_time=datetime(2026, 6, 1, end_hour, 0, tzinfo=UTC),
        space_id=space_id,
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


class _Tracks:
    def list_public_by_event(self, _event_pk):
        return []

    def list_space_pks(self, _track_pk):
        return []


def _service(*, spaces, items, slots, tracks=None):
    return PrintMaterialsService(
        _Events(_event()),
        _ListByEvent(spaces),
        _ListByEvent(items),
        _ListByEvent(slots),
        tracks or _Tracks(),
    )


class TestBuildDoorCards:
    def test_one_card_per_space_in_order(self):
        spaces = [_space(2, "Bravo", 1), _space(1, "Alfa", 0)]
        service = _service(spaces=spaces, items=[], slots=[])

        document = service.build_door_cards(1, UTC)

        assert [c.space_name for c in document.cards] == ["Alfa", "Bravo"]

    def test_empty_slot_rendered_as_gap_alongside_session(self):
        spaces = [_space(1, "Alfa", 0)]
        slots = [_slot(1, 9, 10), _slot(2, 10, 11)]
        items = [_item(1, 1, 9, 10, title="RPG", confirmed=True)]
        service = _service(spaces=spaces, items=items, slots=slots)

        document = service.build_door_cards(1, UTC)

        entries = document.cards[0].days[0].entries
        assert [(e.session.title if e.session else None) for e in entries] == [
            "RPG",
            None,
        ]

    def test_includes_unconfirmed_scheduled_session(self):
        spaces = [_space(1, "Alfa", 0)]
        slots = [_slot(1, 9, 10)]
        items = [_item(1, 1, 9, 10, title="Larp", confirmed=False)]
        service = _service(spaces=spaces, items=items, slots=slots)

        document = service.build_door_cards(1, UTC)

        entries = document.cards[0].days[0].entries
        assert entries[0].session is not None
        assert entries[0].session.title == "Larp"


class TestBuildTimetable:
    def test_rows_per_slot_with_empty_cells_for_unused_spaces(self):
        spaces = [_space(1, "Alfa", 0), _space(2, "Bravo", 1)]
        slots = [_slot(1, 9, 10), _slot(2, 10, 11)]
        items = [_item(1, 1, 9, 10, title="RPG", confirmed=True)]
        service = _service(spaces=spaces, items=items, slots=slots)

        document = service.build_timetable(1, UTC)

        day = document.days[0]
        assert day.space_names == ["Alfa", "Bravo"]
        first_row, second_row = day.rows
        assert [s.title for s in first_row.cells[0].sessions] == ["RPG"]
        assert first_row.cells[1].sessions == []
        assert second_row.cells[0].sessions == []
        assert second_row.cells[1].sessions == []

    def test_session_outside_every_slot_still_appears(self):
        spaces = [_space(1, "Alfa", 0)]
        slots = [_slot(1, 9, 10), _slot(2, 11, 12)]
        # 10:00-11:00 falls in the gap between the two slots.
        items = [_item(1, 1, 10, 11, title="Gap RPG", confirmed=True)]
        service = _service(spaces=spaces, items=items, slots=slots)

        document = service.build_timetable(1, UTC)

        rows = document.days[0].rows
        titles = [s.title for row in rows for cell in row.cells for s in cell.sessions]
        assert titles == ["Gap RPG"]
        gap_start = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
        gap_end = datetime(2026, 6, 1, 11, 0, tzinfo=UTC)
        assert any(
            row.start_time == gap_start and row.end_time == gap_end for row in rows
        )

    def test_sessions_render_when_event_has_no_slots(self):
        spaces = [_space(1, "Alfa", 0)]
        items = [_item(1, 1, 10, 11, title="Solo", confirmed=True)]
        service = _service(spaces=spaces, items=items, slots=[])

        document = service.build_timetable(1, UTC)

        titles = [
            s.title
            for day in document.days
            for row in day.rows
            for cell in row.cells
            for s in cell.sessions
        ]
        assert titles == ["Solo"]

    def test_one_day_per_date(self):
        spaces = [_space(1, "Alfa", 0)]
        slots = [_slot_on_day(1, 1, 9, 10), _slot_on_day(2, 2, 9, 10)]
        service = _service(spaces=spaces, items=[], slots=slots)

        document = service.build_timetable(1, UTC)

        assert [d.day for d in document.days] == [date(2026, 6, 1), date(2026, 6, 2)]

    def test_documents_carry_event_description(self):
        service = _service(spaces=[_space(1, "Alfa", 0)], items=[], slots=[])

        assert service.build_timetable(1, UTC).event_description == "Konwent dla nerdów"
        assert (
            service.build_door_cards(1, UTC).event_description == "Konwent dla nerdów"
        )


class TestConfirmedOnly:
    def test_timetable_drops_unconfirmed_when_confirmed_only(self):
        spaces = [_space(1, "Alfa", 0)]
        items = [
            _item(1, 1, 9, 10, title="Confirmed", confirmed=True),
            _item(2, 1, 10, 11, title="Pending", confirmed=False),
        ]
        service = _service(spaces=spaces, items=items, slots=[])

        document = service.build_timetable(1, UTC, confirmed_only=True)

        titles = [
            s.title
            for day in document.days
            for row in day.rows
            for cell in row.cells
            for s in cell.sessions
        ]
        assert titles == ["Confirmed"]

    def test_door_cards_drop_unconfirmed_when_confirmed_only(self):
        spaces = [_space(1, "Alfa", 0)]
        items = [_item(1, 1, 9, 10, title="Pending", confirmed=False)]
        service = _service(spaces=spaces, items=items, slots=[])

        document = service.build_door_cards(1, UTC, confirmed_only=True)

        sessions = [
            e.session.title
            for card in document.cards
            for day in card.days
            for e in day.entries
            if e.session
        ]
        assert sessions == []


class TestTimetableCompleteness:
    def test_complete_when_every_scheduled_session_confirmed(self):
        spaces = [_space(1, "Alfa", 0)]
        items = [_item(1, 1, 9, 10, title="RPG", confirmed=True)]
        service = _service(spaces=spaces, items=items, slots=[])

        assert service.build_timetable(1, UTC).is_complete is True

    def test_incomplete_when_a_scheduled_session_is_unconfirmed(self):
        spaces = [_space(1, "Alfa", 0)]
        items = [
            _item(1, 1, 9, 10, title="RPG", confirmed=True),
            _item(2, 1, 10, 11, title="Maybe", confirmed=False),
        ]
        service = _service(spaces=spaces, items=items, slots=[])

        # Completeness reflects the whole program, even when the public view is
        # confirmed-only — a pending session means the paper is partial.
        assert service.build_timetable(1, UTC, confirmed_only=True).is_complete is False

    def test_incomplete_when_nothing_scheduled(self):
        spaces = [_space(1, "Alfa", 0)]
        service = _service(spaces=spaces, items=[], slots=[])

        assert service.build_timetable(1, UTC).is_complete is False

    def test_scoped_timetable_is_never_complete(self):
        # A scoped print (one venue/area) is a subset, so never "the whole thing".
        spaces = [_space(1, "Alfa", 0, area_id=10)]
        items = [_item(1, 1, 9, 10, title="RPG", confirmed=True)]
        service = _service(spaces=spaces, items=items, slots=[])

        document = service.build_timetable(1, UTC, area_pks=frozenset({10}))

        assert document.is_complete is False


class TestBuildAreaSchedule:
    def test_sessions_within_range_carry_full_description(self):
        spaces = [_space(1, "Alfa", 0)]
        items = [
            _item(1, 1, 10, 11, title="RPG", confirmed=True, description="A long tale")
        ]
        service = _service(spaces=spaces, items=items, slots=[])
        window = (
            datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
            datetime(2026, 6, 1, 15, 0, tzinfo=UTC),
        )

        document = service.build_area_schedule(1, window)

        space = document.spaces[0]
        assert space.space_name == "Alfa"
        assert [s.title for s in space.sessions] == ["RPG"]
        assert space.sessions[0].description == "A long tale"

    def test_sessions_outside_range_are_excluded(self):
        spaces = [_space(1, "Alfa", 0)]
        items = [_item(1, 1, 20, 21, title="Late night", confirmed=True)]
        service = _service(spaces=spaces, items=items, slots=[])
        window = (
            datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
            datetime(2026, 6, 1, 15, 0, tzinfo=UTC),
        )

        document = service.build_area_schedule(1, window)

        assert document.spaces[0].sessions == []

    def test_confirmed_only_excludes_pending_sessions(self):
        spaces = [_space(1, "Alfa", 0)]
        items = [_item(1, 1, 10, 11, title="Pending", confirmed=False)]
        service = _service(spaces=spaces, items=items, slots=[])
        window = (
            datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
            datetime(2026, 6, 1, 15, 0, tzinfo=UTC),
        )

        document = service.build_area_schedule(1, window, confirmed_only=True)

        assert document.spaces[0].sessions == []

    def test_carries_range_bounds(self):
        spaces = [_space(1, "Alfa", 0)]
        service = _service(spaces=spaces, items=[], slots=[])
        window = (
            datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
            datetime(2026, 6, 1, 15, 0, tzinfo=UTC),
        )

        document = service.build_area_schedule(1, window)

        assert document.range_start == window[0]
        assert document.range_end == window[1]


class TestScoping:
    @staticmethod
    def _scoped_service():
        spaces = [
            _space(1, "Alfa", 0, area_id=10),
            _space(2, "Bravo", 1, area_id=20),
            _space(3, "Cesarz", 2, area_id=30),
        ]
        return _service(spaces=spaces, items=[], slots=[_slot(1, 9, 10)])

    def test_timetable_filtered_to_area_pks(self):
        document = self._scoped_service().build_timetable(
            1, UTC, area_pks=frozenset({10, 20}), scope_name="Budynek A"
        )

        assert document.days[0].space_names == ["Alfa", "Bravo"]
        assert document.scope_name == "Budynek A"

    def test_door_cards_filtered_to_single_area(self):
        document = self._scoped_service().build_door_cards(
            1, UTC, area_pks=frozenset({10}), scope_name="Parter"
        )

        assert [c.space_name for c in document.cards] == ["Alfa"]
        assert document.scope_name == "Parter"

    def test_unscoped_has_no_scope_name(self):
        document = self._scoped_service().build_timetable(1, UTC)

        assert document.scope_name is None
        assert document.days[0].space_names == ["Alfa", "Bravo", "Cesarz"]

    def test_orphan_session_outside_scope_adds_no_row(self):
        # An un-slotted session lives in Cesarz (area 30), outside the scoped
        # area 10 — it must not spawn a fallback row in the scoped grid.
        spaces = [_space(1, "Alfa", 0, area_id=10), _space(3, "Cesarz", 2, area_id=30)]
        items = [_item(1, 3, 12, 13, title="Out of scope", confirmed=True)]
        service = _service(spaces=spaces, items=items, slots=[_slot(1, 9, 10)])

        document = service.build_timetable(1, UTC, area_pks=frozenset({10}))

        day = document.days[0]
        assert day.space_names == ["Alfa"]
        slot_row = (
            datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
            datetime(2026, 6, 1, 10, 0, tzinfo=UTC),
        )
        assert [(r.start_time, r.end_time) for r in day.rows] == [slot_row]
        titles = [s.title for r in day.rows for c in r.cells for s in c.sessions]
        assert titles == []
