"""Printing subdomain business logic.

Assembles the printable materials of the public ``/print`` page (per-room-and-day
door cards, a printed timetable, description-rich per-area time-range pages, and
the participants' session list)
from scheduled agenda items. Queries default to confirmed sessions only;
``confirmed_only=False`` (the sphere managers' toggle) also includes the
unconfirmed ones. The timetable draws an idle room as an empty column; door cards
are participant-facing and list only rooms and hours that actually hold a session.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from functools import partial
from itertools import pairwise
from typing import TYPE_CHECKING

from ludamus.pacts.printing import (
    AreaScheduleDocumentDTO,
    AreaScheduleSessionDTO,
    AreaScheduleSpaceDTO,
    DoorCardDTO,
    DoorCardEntryDTO,
    DoorCardsDocumentDTO,
    PrintablesReadyNotification,
    PrintablesReminderServiceProtocol,
    PrintOptionDTO,
    PrintQueryDTO,
    PrintSessionDTO,
    PrintSessionListDocumentDTO,
    PrintSessionListItemDTO,
    PrintTimetableDocumentDTO,
    PrintTimetablePageDTO,
    PrintTimetableRowDTO,
    PrintTimetableTileDTO,
)

if TYPE_CHECKING:
    from datetime import date, datetime

    from ludamus.pacts import (
        AgendaItemDTO,
        AgendaItemRepositoryProtocol,
        EventRepositoryProtocol,
        SpaceDTO,
        SpaceRepositoryProtocol,
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


def _space_order(space: SpaceDTO) -> tuple[int, str, int]:
    return (space.programme_order, space.name, space.pk)


def _session_list_order(
    item: AgendaItemDTO, space_order: dict[int, tuple[int, str, int]]
) -> tuple[datetime, tuple[int, str, int]]:
    fallback = (len(space_order), item.space_name, item.space_id)
    return (item.start_time, space_order.get(item.space_id, fallback))


def _space_chunks(spaces: list[SpaceDTO]) -> list[list[SpaceDTO]]:
    return [
        spaces[index : index + MAX_TIMETABLE_SPACES_PER_PAGE]
        for index in range(0, len(spaces), MAX_TIMETABLE_SPACES_PER_PAGE)
    ]


def _space_range_name(spaces: list[SpaceDTO]) -> str | None:
    if len(spaces) <= 1:
        return None
    return f"{spaces[0].name} - {spaces[-1].name}"


def _timetable_page(
    *, day: date, spaces: list[SpaceDTO], items: list[AgendaItemDTO]
) -> PrintTimetablePageDTO | None:
    # One sheet: the day's sessions in these rooms, or None when there are
    # none. Rows are the stretches between the instants the programme
    # changes, so a session is one tile spanning exactly the rows it covers —
    # the shape of the event page's rooms view. Time slots are proposer
    # availability windows, not display units (see mills/timeslots.py), so
    # they play no part here. Instants are keyed as timestamps: on the night
    # the clocks go back two datetimes an hour apart compare equal.
    col = {space.pk: index + 1 for index, space in enumerate(spaces)}
    if not (items := [item for item in items if item.space_id in col]):
        return None
    instants = {
        instant.timestamp(): instant
        for item in items
        for instant in (item.start_time, item.end_time)
    }
    keys = sorted(instants)
    edges = [instants[key] for key in keys]
    line = {key: index + 1 for index, key in enumerate(keys)}

    def reading_order(item: AgendaItemDTO) -> tuple[int, int]:
        # Down the rows, then across the columns: the visual order.
        return (line[item.start_time.timestamp()], col[item.space_id])

    return PrintTimetablePageDTO(
        day=day,
        space_names=[space.name for space in spaces],
        rows=[
            PrintTimetableRowDTO(start_time=start, end_time=end)
            for start, end in pairwise(edges)
        ],
        tiles=[
            PrintTimetableTileDTO(
                session=_to_session(item),
                start_time=item.start_time,
                end_time=item.end_time,
                col=col[item.space_id],
                row=line[item.start_time.timestamp()],
                span=line[item.end_time.timestamp()]
                - line[item.start_time.timestamp()],
            )
            for item in sorted(items, key=reading_order)
        ],
        space_range_name=_space_range_name(spaces),
    )


class PrintMaterialsService:
    def __init__(
        self,
        events: EventRepositoryProtocol,
        spaces: SpaceRepositoryProtocol,
        agenda_items: AgendaItemRepositoryProtocol,
        tracks: TrackRepositoryProtocol,
    ) -> None:
        self._events = events
        self._spaces = spaces
        self._agenda_items = agenda_items
        self._tracks = tracks

    def list_tracks(self, event_pk: int) -> list[PrintOptionDTO]:
        return [
            PrintOptionDTO(pk=track.pk, name=track.name, slug=track.slug)
            for track in self._tracks.list_public_by_event(event_pk)
        ]

    def build_door_cards(self, query: PrintQueryDTO) -> DoorCardsDocumentDTO:
        event = self._events.read(query.event_pk)
        spaces = self._scoped_spaces(
            query.event_pk, query.scope_space_pks, query.track_pk
        )
        items = self._agenda_items.list_by_event(query.event_pk, public_only=True)
        if query.time_range is not None:
            items = [item for item in items if _overlaps(item, *query.time_range)]
        items_by_space = self._group_by_space(
            items, confirmed_only=query.confirmed_only
        )

        cards: list[DoorCardDTO] = []
        for space in spaces:
            # Cards hang on doors for participants: a room with nothing
            # scheduled gets no card, and empty hours are simply not listed.
            entries_by_day: dict[date, list[DoorCardEntryDTO]] = defaultdict(list)

            for item in items_by_space.get(space.pk, []):
                day = item.start_time.astimezone(query.tz).date()
                entries_by_day[day].append(
                    DoorCardEntryDTO(
                        start_time=item.start_time,
                        end_time=item.end_time,
                        session=_to_session(item),
                    )
                )

            cards += [
                DoorCardDTO(
                    space_name=space.name,
                    capacity=space.capacity,
                    day=day,
                    entries=sorted(entries_by_day[day], key=_entry_start),
                )
                for day in sorted(entries_by_day)
            ]

        return DoorCardsDocumentDTO(
            event_name=event.name,
            event_description=event.description,
            event_start=event.start_time,
            event_end=event.end_time,
            scope_name=query.scope_name,
            cards=cards,
        )

    def build_timetable(self, query: PrintQueryDTO) -> PrintTimetableDocumentDTO:
        event = self._events.read(query.event_pk)
        spaces = self._scoped_spaces(
            query.event_pk, query.scope_space_pks, query.track_pk
        )
        all_items = (
            self._agenda_items.list_by_track(query.track_pk, public_only=True)
            if query.track_pk is not None
            else self._agenda_items.list_by_event(query.event_pk, public_only=True)
        )
        if query.time_range is not None:
            all_items = [
                item for item in all_items if _overlaps(item, *query.time_range)
            ]
        # One sheet per day and space chunk that holds anything.
        space_pks = {space.pk for space in spaces}
        by_day: dict[date, list[AgendaItemDTO]] = defaultdict(list)
        for item in all_items:
            if item.space_id in space_pks and (
                item.session_confirmed or not query.confirmed_only
            ):
                by_day[item.start_time.astimezone(query.tz).date()].append(item)
        pages = [
            page
            for day in sorted(by_day)
            for chunk in _space_chunks(spaces)
            if (page := _timetable_page(day=day, spaces=chunk, items=by_day[day]))
        ]

        return PrintTimetableDocumentDTO(
            event_name=event.name,
            event_description=event.description,
            event_start=event.start_time,
            event_end=event.end_time,
            scope_name=query.scope_name,
            # A scoped print (space subtree, track, or time range) is a subset
            # by construction, so it is never "the whole program"; completeness
            # only applies unscoped.
            is_complete=(
                query.scope_space_pks is None
                and query.track_pk is None
                and query.time_range is None
                and _is_complete(all_items)
            ),
            pages=pages,
        )

    def build_area_schedule(self, query: PrintQueryDTO) -> AreaScheduleDocumentDTO:
        event = self._events.read(query.event_pk)
        range_start, range_end = query.time_range or (event.start_time, event.end_time)
        spaces = self._scoped_spaces(
            query.event_pk, query.scope_space_pks, query.track_pk
        )
        items = (
            self._agenda_items.list_by_track(query.track_pk, public_only=True)
            if query.track_pk is not None
            else self._agenda_items.list_by_event(query.event_pk, public_only=True)
        )
        if query.time_range is not None:
            items = [item for item in items if _overlaps(item, *query.time_range)]
        grouped = self._group_by_space(items, confirmed_only=query.confirmed_only)

        space_dtos: list[AreaScheduleSpaceDTO] = []
        for space in spaces:
            sessions: list[AreaScheduleSessionDTO] = []
            for item in grouped.get(space.pk, []):
                sessions.append(
                    AreaScheduleSessionDTO(
                        title=item.session_title,
                        presenter_name=item.presenter_name,
                        description=item.session_description,
                        start_time=item.start_time,
                        end_time=item.end_time,
                    )
                )
                if query.time_range is None:
                    range_start = min(range_start, item.start_time)
                    range_end = max(range_end, item.end_time)
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

    def build_session_list(self, query: PrintQueryDTO) -> PrintSessionListDocumentDTO:
        # Unscoped by design: a participant walks the whole venue.
        event = self._events.read(query.event_pk)
        items = [
            item
            for item in self._agenda_items.list_by_event(
                query.event_pk, public_only=True
            )
            if item.session_confirmed or not query.confirmed_only
        ]
        space_order = {
            space.pk: _space_order(space)
            for space in self._spaces.list_by_event(query.event_pk)
        }
        return PrintSessionListDocumentDTO(
            event_name=event.name,
            event_description=event.description,
            event_start=event.start_time,
            event_end=event.end_time,
            sessions=[
                PrintSessionListItemDTO(
                    title=item.session_title,
                    presenter_name=item.presenter_name,
                    description=item.session_description,
                    start_time=item.start_time,
                    end_time=item.end_time,
                    space_name=item.space_name,
                )
                for item in sorted(
                    items, key=partial(_session_list_order, space_order=space_order)
                )
            ],
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

    def send_due_reminders(self, *, now: datetime) -> int:
        due = self._reminders.list_pending_reminders(
            now=now, lead_time=PRINTABLES_REMINDER_LEAD_TIME
        )
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
                            event_slug=reminder.event_slug,
                            sphere_domain=reminder.sphere_domain,
                        )
                    )
        return len(due)
