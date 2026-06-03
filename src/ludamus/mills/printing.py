"""Printing subdomain business logic.

Assembles organizer-facing printable materials (per-room door cards and a
printed timetable) from scheduled agenda items. Includes every scheduled
session regardless of the confirmed flag, and renders empty time slots as
explicit gaps.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from ludamus.mills.timeslots import slot_windows_by_local_date
from ludamus.pacts.printing import (
    DoorCardDayDTO,
    DoorCardDTO,
    DoorCardEntryDTO,
    DoorCardsDocumentDTO,
    PrintSessionDTO,
    PrintTimetableCellDTO,
    PrintTimetableDayDTO,
    PrintTimetableDocumentDTO,
    PrintTimetableRowDTO,
)

if TYPE_CHECKING:
    from datetime import date, datetime, tzinfo

    from ludamus.pacts import (
        AgendaItemDTO,
        AgendaItemRepositoryProtocol,
        EventRepositoryProtocol,
        SpaceDTO,
        SpaceRepositoryProtocol,
        TimeSlotRepositoryProtocol,
    )


def _to_session(item: AgendaItemDTO) -> PrintSessionDTO:
    return PrintSessionDTO(
        title=item.session_title,
        presenter_name=item.presenter_name,
        category_name=item.category_name,
        start_time=item.start_time,
        end_time=item.end_time,
    )


def _overlaps(item: AgendaItemDTO, start: datetime, end: datetime) -> bool:
    return item.start_time < end and item.end_time > start


def _entry_start(entry: DoorCardEntryDTO) -> datetime:
    return entry.start_time


def _space_order(space: SpaceDTO) -> tuple[int, str]:
    return (space.order, space.name)


class PrintMaterialsService:
    """Read-side assembler for printable PDF materials."""

    def __init__(
        self,
        events: EventRepositoryProtocol,
        spaces: SpaceRepositoryProtocol,
        agenda_items: AgendaItemRepositoryProtocol,
        time_slots: TimeSlotRepositoryProtocol,
    ) -> None:
        self._events = events
        self._spaces = spaces
        self._agenda_items = agenda_items
        self._time_slots = time_slots

    def build_door_cards(self, event_pk: int, tz: tzinfo) -> DoorCardsDocumentDTO:
        event = self._events.read(event_pk)
        spaces = self._ordered_spaces(event_pk)
        items_by_space = self._items_by_space(event_pk)
        windows_by_date = slot_windows_by_local_date(
            self._time_slots.list_by_event(event_pk), tz
        )

        cards: list[DoorCardDTO] = []
        for space in spaces:
            space_items = items_by_space.get(space.pk, [])
            entries_by_day: dict[date, list[DoorCardEntryDTO]] = defaultdict(list)

            for item in space_items:
                day = item.start_time.astimezone(tz).date()
                entries_by_day[day].append(
                    DoorCardEntryDTO(
                        start_time=item.start_time,
                        end_time=item.end_time,
                        session=_to_session(item),
                    )
                )

            for day, windows in windows_by_date.items():
                for window_start, window_end in windows:
                    if not any(
                        _overlaps(item, window_start, window_end)
                        for item in space_items
                    ):
                        entries_by_day[day].append(
                            DoorCardEntryDTO(
                                start_time=window_start,
                                end_time=window_end,
                                session=None,
                            )
                        )

            days = [
                DoorCardDayDTO(
                    day=day, entries=sorted(entries_by_day[day], key=_entry_start)
                )
                for day in sorted(entries_by_day)
            ]
            cards.append(
                DoorCardDTO(space_name=space.name, capacity=space.capacity, days=days)
            )

        return DoorCardsDocumentDTO(
            event_name=event.name,
            event_start=event.start_time,
            event_end=event.end_time,
            cards=cards,
        )

    def build_timetable(self, event_pk: int, tz: tzinfo) -> PrintTimetableDocumentDTO:
        event = self._events.read(event_pk)
        spaces = self._ordered_spaces(event_pk)
        items_by_space = self._items_by_space(event_pk)
        windows_by_date = slot_windows_by_local_date(
            self._time_slots.list_by_event(event_pk), tz
        )
        space_names = [space.name for space in spaces]

        days: list[PrintTimetableDayDTO] = []
        for day in sorted(windows_by_date):
            rows: list[PrintTimetableRowDTO] = []
            for window_start, window_end in sorted(windows_by_date[day]):
                cells: list[PrintTimetableCellDTO] = []
                for space in spaces:
                    sessions = [
                        _to_session(item)
                        for item in items_by_space.get(space.pk, [])
                        if _overlaps(item, window_start, window_end)
                    ]
                    cells.append(PrintTimetableCellDTO(sessions=sessions))
                rows.append(
                    PrintTimetableRowDTO(
                        start_time=window_start, end_time=window_end, cells=cells
                    )
                )
            days.append(
                PrintTimetableDayDTO(day=day, space_names=space_names, rows=rows)
            )

        return PrintTimetableDocumentDTO(
            event_name=event.name,
            event_start=event.start_time,
            event_end=event.end_time,
            days=days,
        )

    def _ordered_spaces(self, event_pk: int) -> list[SpaceDTO]:
        return sorted(self._spaces.list_by_event(event_pk), key=_space_order)

    def _items_by_space(self, event_pk: int) -> dict[int, list[AgendaItemDTO]]:
        items_by_space: dict[int, list[AgendaItemDTO]] = defaultdict(list)
        for item in self._agenda_items.list_by_event(event_pk):
            items_by_space[item.space_id].append(item)
        for items in items_by_space.values():
            items.sort(key=lambda x: x.start_time)
        return items_by_space
