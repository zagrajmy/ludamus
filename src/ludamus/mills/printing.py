"""Printing subdomain business logic.

Assembles printable materials (per-room door cards, a printed timetable, and
description-rich per-area time-range pages) from scheduled agenda items. The
organizer-facing materials include every scheduled session; passing
``confirmed_only=True`` (the public ``/print`` page) keeps only confirmed ones.
Empty time slots render as explicit gaps.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import TYPE_CHECKING

from ludamus.mills.timeslots import slot_windows_by_local_date
from ludamus.pacts.printing import (
    AreaScheduleDocumentDTO,
    AreaScheduleQueryDTO,
    AreaScheduleSessionDTO,
    AreaScheduleSpaceDTO,
    DoorCardDayDTO,
    DoorCardDTO,
    DoorCardEntryDTO,
    DoorCardsDocumentDTO,
    PrintablesReadyNotification,
    PrintablesReminderServiceProtocol,
    PrintOptionDTO,
    PrintSessionDTO,
    PrintSessionListDocumentDTO,
    PrintSessionListItemDTO,
    PrintTimetableCellDTO,
    PrintTimetableDocumentDTO,
    PrintTimetablePageDTO,
    PrintTimetableQueryDTO,
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
    from ludamus.pacts.printing import (
        PrintablesNotifierProtocol,
        PrintablesReminderRepositoryProtocol,
    )
    from ludamus.pacts.services import TransactionProtocol


MAX_TIMETABLE_SPACES_PER_PAGE = 4


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


def _session_list_order(item: AgendaItemDTO) -> tuple[datetime, str]:
    return (item.start_time, item.space_name)


def _space_chunks(spaces: list[SpaceDTO]) -> list[list[SpaceDTO]]:
    return [
        spaces[index : index + MAX_TIMETABLE_SPACES_PER_PAGE]
        for index in range(0, len(spaces), MAX_TIMETABLE_SPACES_PER_PAGE)
    ]


def _space_range_name(spaces: list[SpaceDTO]) -> str | None:
    if len(spaces) <= 1:
        return None
    return f"{spaces[0].name} - {spaces[-1].name}"


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
        scope_space_pks: frozenset[int] | None = None,
        scope_name: str | None = None,
        confirmed_only: bool = False,
    ) -> DoorCardsDocumentDTO:
        event = self._events.read(event_pk)
        spaces = self._scoped_spaces(event_pk, scope_space_pks, None)
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
        self, query: PrintTimetableQueryDTO
    ) -> PrintTimetableDocumentDTO:
        event = self._events.read(query.event_pk)
        spaces = self._scoped_spaces(
            query.event_pk, query.scope_space_pks, query.track_pk
        )
        all_items = (
            self._agenda_items.list_by_track(query.track_pk)
            if query.track_pk is not None
            else self._agenda_items.list_by_event(query.event_pk)
        )
        grouped = self._group_by_space(all_items, confirmed_only=query.confirmed_only)
        items_by_space = {space.pk: grouped.get(space.pk, []) for space in spaces}
        windows_by_date = slot_windows_by_local_date(
            self._time_slots.list_by_event(query.event_pk), query.tz
        )
        rows_by_date = _timetable_rows_by_date(
            windows_by_date, items_by_space, query.tz
        )

        pages: list[PrintTimetablePageDTO] = []
        for day in sorted(rows_by_date):
            for space_chunk in _space_chunks(spaces):
                rows: list[PrintTimetableRowDTO] = []
                for window_start, window_end in rows_by_date[day]:
                    cells: list[PrintTimetableCellDTO] = []
                    for space in space_chunk:
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
                pages.append(
                    PrintTimetablePageDTO(
                        day=day,
                        space_names=[space.name for space in space_chunk],
                        rows=rows,
                        space_range_name=_space_range_name(space_chunk),
                    )
                )

        return PrintTimetableDocumentDTO(
            event_name=event.name,
            event_description=event.description,
            event_start=event.start_time,
            event_end=event.end_time,
            scope_name=query.scope_name,
            # A scoped print (one space subtree) is a subset by construction, so
            # it is never "the whole program"; completeness only applies unscoped.
            is_complete=(
                query.scope_space_pks is None
                and query.track_pk is None
                and _is_complete(all_items)
            ),
            pages=pages,
        )

    def build_area_schedule(
        self, query: AreaScheduleQueryDTO
    ) -> AreaScheduleDocumentDTO:
        range_start, range_end = query.time_range
        event = self._events.read(query.event_pk)
        spaces = self._scoped_spaces(query.event_pk, query.scope_space_pks, None)
        grouped = self._group_by_space(
            self._agenda_items.list_by_event(query.event_pk),
            confirmed_only=query.confirmed_only,
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
            scope_name=query.scope_name,
            spaces=space_dtos,
        )

    def build_session_list(
        self, event_pk: int, *, confirmed_only: bool = False
    ) -> PrintSessionListDocumentDTO | None:
        tracks = self._tracks.list_public_by_event(event_pk)
        slots = self._time_slots.list_by_event(event_pk)
        if len(tracks) != 1 or len(slots) != 1:
            return None

        event = self._events.read(event_pk)
        slot = slots[0]
        items: list[AgendaItemDTO] = [
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
            for item in sorted(items, key=_session_list_order)
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
        scope_space_pks: frozenset[int] | None,
        track_pk: int | None,
    ) -> list[SpaceDTO]:
        all_nodes = self._spaces.list_by_event(event_pk)
        # Only leaves (childless nodes) are bookable rooms worth printing.
        parent_pks = {n.parent_id for n in all_nodes if n.parent_id is not None}
        spaces = sorted(
            (s for s in all_nodes if s.pk not in parent_pks), key=_space_order
        )
        if track_pk is not None:
            track_space_pks = frozenset(self._tracks.list_space_pks(track_pk))
            spaces = [s for s in spaces if s.pk in track_space_pks]
        if scope_space_pks is None:
            return spaces
        return [s for s in spaces if s.pk in scope_space_pks]

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


PRINTABLES_REMINDER_LEAD_TIME = timedelta(days=2)


class PrintablesReminderService(PrintablesReminderServiceProtocol):
    """Reminds organizers to print their materials before the event.

    `mark_printed` records that an organizer opened a print-ready page;
    `send_due_reminders` (run periodically) emails organizers of events starting
    within the lead time who have not printed yet, once per event.
    """

    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        reminders: PrintablesReminderRepositoryProtocol,
        notifier: PrintablesNotifierProtocol,
    ) -> None:
        self._transaction = transaction
        self._reminders = reminders
        self._notifier = notifier

    def mark_printed(self, event_pk: int) -> None:
        self._reminders.mark_printed(event_pk)

    def send_due_reminders(
        self, *, now: datetime, lead_time: timedelta = PRINTABLES_REMINDER_LEAD_TIME
    ) -> int:
        due = self._reminders.list_pending_reminders(now=now, lead_time=lead_time)
        for reminder in due:
            # Mark sent inside the same transaction as the notifications so a
            # crash mid-batch never leaves an event marked-but-unnotified; the
            # emails themselves are deferred to after-commit by the notifier.
            with self._transaction.atomic():
                self._reminders.mark_reminder_sent(reminder.event_pk, at=now)
                for recipient in reminder.recipients:
                    self._notifier.notify_printables_ready(
                        PrintablesReadyNotification(
                            recipient_user_id=recipient.user_id,
                            recipient_email=recipient.email,
                            event_name=reminder.event_name,
                            materials_url=reminder.materials_url,
                        )
                    )
        return len(due)
