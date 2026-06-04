"""Printing subdomain business logic.

Assembles printable materials (per-room door cards, a printed timetable, and
description-rich per-area time-range pages) from scheduled agenda items. The
organizer-facing materials include every scheduled session; passing
``confirmed_only=True`` (the public ``/print`` page) keeps only confirmed ones.
Empty time slots render as explicit gaps.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from ludamus.mills.timeslots import slot_windows_by_local_date
from ludamus.pacts.printing import (
    AreaScheduleDocumentDTO,
    AreaScheduleSessionDTO,
    AreaScheduleSpaceDTO,
    DoorCardDayDTO,
    DoorCardDTO,
    DoorCardEntryDTO,
    DoorCardsDocumentDTO,
    PrintOptionDTO,
    PrintSessionDTO,
    PrintSessionListDocumentDTO,
    PrintSessionListItemDTO,
    PrintSpaceOptionDTO,
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
        TrackRepositoryProtocol,
    )


def _to_session(item: AgendaItemDTO) -> PrintSessionDTO:
    return PrintSessionDTO(title=item.session_title, presenter_name=item.presenter_name)


def _is_complete(items: list[AgendaItemDTO]) -> bool:
    # Complete = at least one scheduled session and nothing left unconfirmed;
    # the printed grid is then the whole program rather than a partial view.
    return bool(items) and all(item.session_confirmed for item in items)


def _overlaps(item: AgendaItemDTO, start: datetime, end: datetime) -> bool:
    return item.start_time < end and item.end_time > start


def _entry_start(entry: DoorCardEntryDTO) -> datetime:
    return entry.start_time


def _space_order(space: SpaceDTO) -> tuple[int, str]:
    return (space.order, space.name)


def _timetable_rows_by_date(
    windows_by_date: dict[date, list[tuple[datetime, datetime]]],
    items_by_space: dict[int, list[AgendaItemDTO]],
    tz: tzinfo,
) -> dict[date, list[tuple[datetime, datetime]]]:
    # Rows are the event's time slots, plus a fallback row for any scheduled
    # session that overlaps no slot — so a session placed outside the defined
    # slots (or an event with no slots at all) never silently drops off the
    # grid the way it would if rows came from slots alone.
    rows: dict[date, set[tuple[datetime, datetime]]] = defaultdict(set)
    for day, windows in windows_by_date.items():
        rows[day].update(windows)

    all_windows = [w for windows in windows_by_date.values() for w in windows]
    for items in items_by_space.values():
        for item in items:
            if not any(_overlaps(item, ws, we) for ws, we in all_windows):
                day = item.start_time.astimezone(tz).date()
                rows[day].add((item.start_time, item.end_time))

    return {day: sorted(intervals) for day, intervals in rows.items()}


class PrintMaterialsService:
    def __init__(
        self,
        events: EventRepositoryProtocol,
        spaces: SpaceRepositoryProtocol,
        agenda_items: AgendaItemRepositoryProtocol,
        time_slots: TimeSlotRepositoryProtocol,
        tracks: TrackRepositoryProtocol,
    ) -> None:
        self._events = events
        self._spaces = spaces
        self._agenda_items = agenda_items
        self._time_slots = time_slots
        self._tracks = tracks

    def list_spaces(self, event_pk: int) -> list[PrintSpaceOptionDTO]:
        return [
            PrintSpaceOptionDTO(
                pk=space.pk,
                name=space.name,
                slug=space.slug,
                area_id=space.area_id,
            )
            for space in self._scoped_spaces(event_pk, None, None, None)
        ]

    def list_tracks(self, event_pk: int) -> list[PrintOptionDTO]:
        return [
            PrintOptionDTO(pk=track.pk, name=track.name, slug=track.slug)
            for track in self._tracks.list_public_by_event(event_pk)
        ]

    def build_door_cards(
        self,
        event_pk: int,
        tz: tzinfo,
        *,
        area_pks: frozenset[int] | None = None,
        scope_name: str | None = None,
        confirmed_only: bool = False,
    ) -> DoorCardsDocumentDTO:
        event = self._events.read(event_pk)
        spaces = self._scoped_spaces(event_pk, area_pks, None, None)
        items_by_space = self._group_by_space(
            self._agenda_items.list_by_event(event_pk), confirmed_only=confirmed_only
        )
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
            event_description=event.description,
            event_start=event.start_time,
            event_end=event.end_time,
            scope_name=scope_name,
            cards=cards,
        )

    def build_timetable(
        self,
        event_pk: int,
        tz: tzinfo,
        *,
        area_pks: frozenset[int] | None = None,
        space_pks: frozenset[int] | None = None,
        track_pk: int | None = None,
        scope_name: str | None = None,
        confirmed_only: bool = False,
    ) -> PrintTimetableDocumentDTO:
        event = self._events.read(event_pk)
        spaces = self._scoped_spaces(event_pk, area_pks, space_pks, track_pk)
        all_items = (
            self._agenda_items.list_by_track(track_pk)
            if track_pk is not None
            else self._agenda_items.list_by_event(event_pk)
        )
        grouped = self._group_by_space(all_items, confirmed_only=confirmed_only)
        items_by_space = {space.pk: grouped.get(space.pk, []) for space in spaces}
        windows_by_date = slot_windows_by_local_date(
            self._time_slots.list_by_event(event_pk), tz
        )
        space_names = [space.name for space in spaces]
        rows_by_date = _timetable_rows_by_date(windows_by_date, items_by_space, tz)

        days: list[PrintTimetableDayDTO] = []
        for day in sorted(rows_by_date):
            rows: list[PrintTimetableRowDTO] = []
            for window_start, window_end in rows_by_date[day]:
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
            event_description=event.description,
            event_start=event.start_time,
            event_end=event.end_time,
            scope_name=scope_name,
            # A scoped print (one venue/area) is a subset by construction, so it
            # is never "the whole program"; completeness only applies unscoped.
            is_complete=(
                area_pks is None
                and space_pks is None
                and track_pk is None
                and _is_complete(all_items)
            ),
            days=days,
        )

    def build_area_schedule(
        self,
        event_pk: int,
        time_range: tuple[datetime, datetime],
        *,
        area_pks: frozenset[int] | None = None,
        space_pks: frozenset[int] | None = None,
        scope_name: str | None = None,
        confirmed_only: bool = False,
    ) -> AreaScheduleDocumentDTO:
        range_start, range_end = time_range
        event = self._events.read(event_pk)
        spaces = self._scoped_spaces(event_pk, area_pks, space_pks, None)
        grouped = self._group_by_space(
            self._agenda_items.list_by_event(event_pk), confirmed_only=confirmed_only
        )

        space_dtos: list[AreaScheduleSpaceDTO] = []
        for space in spaces:
            sessions = [
                AreaScheduleSessionDTO(
                    title=item.session_title,
                    presenter_name=item.presenter_name,
                    description=item.session_description,
                    start_time=item.start_time,
                    end_time=item.end_time,
                )
                for item in grouped.get(space.pk, [])
                if _overlaps(item, range_start, range_end)
            ]
            space_dtos.append(
                AreaScheduleSpaceDTO(
                    space_name=space.name, capacity=space.capacity, sessions=sessions
                )
            )

        return AreaScheduleDocumentDTO(
            event_name=event.name,
            event_description=event.description,
            event_start=event.start_time,
            event_end=event.end_time,
            range_start=range_start,
            range_end=range_end,
            scope_name=scope_name,
            spaces=space_dtos,
        )

    def build_session_list(
        self,
        event_pk: int,
        *,
        confirmed_only: bool = False,
    ) -> PrintSessionListDocumentDTO | None:
        tracks = self._tracks.list_public_by_event(event_pk)
        slots = self._time_slots.list_by_event(event_pk)
        if len(tracks) != 1 or len(slots) != 1:
            return None

        event = self._events.read(event_pk)
        slot = slots[0]
        items = [
            item
            for item in self._agenda_items.list_by_track(tracks[0].pk)
            if _overlaps(item, slot.start_time, slot.end_time)
            and (item.session_confirmed or not confirmed_only)
        ]
        sessions = [
            PrintSessionListItemDTO(
                title=item.session_title,
                presenter_name=item.presenter_name,
                description=item.session_description,
                start_time=item.start_time,
                end_time=item.end_time,
                space_name=item.space_name,
            )
            for item in sorted(items, key=lambda i: (i.start_time, i.space_name))
        ]
        return PrintSessionListDocumentDTO(
            event_name=event.name,
            event_description=event.description,
            event_start=event.start_time,
            event_end=event.end_time,
            scope_name=tracks[0].name,
            sessions=sessions,
        )

    def _scoped_spaces(
        self,
        event_pk: int,
        area_pks: frozenset[int] | None,
        space_pks: frozenset[int] | None,
        track_pk: int | None,
    ) -> list[SpaceDTO]:
        spaces = sorted(self._spaces.list_by_event(event_pk), key=_space_order)
        if track_pk is not None:
            track_space_pks = frozenset(self._tracks.list_space_pks(track_pk))
            if track_space_pks:
                spaces = [s for s in spaces if s.pk in track_space_pks]
        if area_pks is None:
            scoped = spaces
        else:
            scoped = [s for s in spaces if s.area_id in area_pks]
        if space_pks is None:
            return scoped
        return [s for s in scoped if s.pk in space_pks]

    @staticmethod
    def _group_by_space(
        items: list[AgendaItemDTO], *, confirmed_only: bool
    ) -> dict[int, list[AgendaItemDTO]]:
        items_by_space: dict[int, list[AgendaItemDTO]] = defaultdict(list)
        for item in items:
            if confirmed_only and not item.session_confirmed:
                continue
            items_by_space[item.space_id].append(item)
        for grouped in items_by_space.values():
            grouped.sort(key=lambda x: x.start_time)
        return items_by_space
