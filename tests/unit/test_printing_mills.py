from datetime import UTC, datetime

from ludamus.mills.printing import PrintMaterialsService
from ludamus.pacts import AgendaItemDTO, EventDTO, SpaceDTO, TimeSlotDTO


def _event():
    return EventDTO(
        description="",
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


def _space(pk, name, order):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return SpaceDTO(
        area_id=None,
        capacity=20,
        creation_time=now,
        modification_time=now,
        name=name,
        order=order,
        pk=pk,
        slug=name.lower(),
    )


def _slot(pk, start_hour, end_hour):
    return TimeSlotDTO(
        pk=pk,
        start_time=datetime(2026, 6, 1, start_hour, 0, tzinfo=UTC),
        end_time=datetime(2026, 6, 1, end_hour, 0, tzinfo=UTC),
    )


def _item(pk, space_id, start_hour, end_hour, *, title, confirmed):
    return AgendaItemDTO(
        pk=pk,
        session_confirmed=confirmed,
        start_time=datetime(2026, 6, 1, start_hour, 0, tzinfo=UTC),
        end_time=datetime(2026, 6, 1, end_hour, 0, tzinfo=UTC),
        space_id=space_id,
        session_title=title,
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


def _service(*, spaces, items, slots):
    return PrintMaterialsService(
        _Events(_event()),
        _ListByEvent(spaces),
        _ListByEvent(items),
        _ListByEvent(slots),
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
