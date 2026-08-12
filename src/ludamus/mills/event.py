from collections import Counter, defaultdict
from datetime import UTC, datetime

from ludamus.pacts.event import (
    ConfirmationDashboardDTO,
    ConfirmationEmailGroupDTO,
    ConfirmationFacilitatorDTO,
    ConfirmationOrganizerRowDTO,
    ConfirmationSessionDTO,
    ConfirmationStatusGroupDTO,
    ConfirmationTrackRowDTO,
    ConfirmationTrackViewDTO,
    EventConfirmationsServiceProtocol,
    EventPanelContextDTO,
    EventPanelServiceProtocol,
    LandingStatsDTO,
    LandingStatsRepositoryProtocol,
)
from ludamus.pacts.legacy import (
    AgendaItemRepositoryProtocol,
    ConfirmationCountsRow,
    ConfirmationFacilitatorRow,
    ConfirmationSessionRow,
    EventDTO,
    EventRepositoryProtocol,
    EventStatsData,
    FacilitatorRepositoryProtocol,
    NotFoundError,
    PanelStatsDTO,
    SessionRepositoryProtocol,
    SessionStatus,
    TrackRepositoryProtocol,
)
from ludamus.specs.confirmations import COUNTED_UNPLACED, SCHEDULED_STATUS, STATUS_ORDER


# Panel access only proves you manage an event; every id the request names has
# to be scoped to it before it is read or written, or it is cross-event
# tampering. Both guards live on the event noun because that is what they
# assert membership of, and every panel service needs one or the other.
def require_session_in_event(
    *, sessions: SessionRepositoryProtocol, session_pk: int, event_pk: int
) -> None:
    if sessions.read_event(session_pk).pk != event_pk:
        raise NotFoundError


def require_track_in_event(
    *, tracks: TrackRepositoryProtocol, track_pk: int, event_pk: int
) -> None:
    if tracks.read(track_pk).event_id != event_pk:
        raise NotFoundError


def is_proposal_active(event: EventDTO) -> bool:
    current_time = datetime.now(tz=UTC)
    return bool(
        event.publication_time is not None
        and event.publication_time <= current_time
        and event.proposal_start_time is not None
        and event.proposal_end_time is not None
        and event.proposal_start_time <= current_time <= event.proposal_end_time
    )


def build_panel_stats(stats_data: EventStatsData) -> PanelStatsDTO:
    return PanelStatsDTO(
        total_sessions=stats_data.pending_proposals + stats_data.scheduled_sessions,
        scheduled_sessions=stats_data.scheduled_sessions,
        pending_proposals=stats_data.pending_proposals,
        hosts_count=stats_data.hosts_count,
        rooms_count=stats_data.rooms_count,
        total_proposals=stats_data.total_proposals,
    )


def _progress_pct(*, confirmed: int, scheduled: int) -> int:
    return round(confirmed * 100 / scheduled) if scheduled else 0


class EventConfirmationsService(EventConfirmationsServiceProtocol):
    """Post-schedule confirmation tracking for one event."""

    def __init__(
        self,
        *,
        facilitators: FacilitatorRepositoryProtocol,
        agenda_items: AgendaItemRepositoryProtocol,
        tracks: TrackRepositoryProtocol,
        sessions: SessionRepositoryProtocol,
    ) -> None:
        self._facilitators = facilitators
        self._agenda_items = agenda_items
        self._tracks = tracks
        self._sessions = sessions

    def track_view(self, *, event_pk: int, track_pk: int) -> ConfirmationTrackViewDTO:
        facilitator_rows = self._facilitators.list_with_scheduled_session_in_track(
            event_pk, track_pk
        )
        orphans = self._agenda_items.count_without_facilitator(event_pk, track_pk)
        # Nobody in the block means nothing to look up: the assembly below
        # already yields an empty view, it just does not need three queries.
        session_rows = (
            self._sessions.list_confirmation_rows(
                event_pk, [row["pk"] for row in facilitator_rows]
            )
            if facilitator_rows
            else []
        )
        session_pks = [row["session_pk"] for row in session_rows]
        track_names = (
            self._sessions.list_track_names_by_session(session_pks)
            if session_pks
            else {}
        )
        facilitator_names = (
            self._sessions.list_facilitator_names_by_session(session_pks)
            if session_pks
            else {}
        )

        by_facilitator: dict[int, list[ConfirmationSessionRow]] = defaultdict(list)
        for row in session_rows:
            by_facilitator[row["facilitator_pk"]].append(row)

        facilitators = [
            _facilitator(
                row=row,
                sessions=by_facilitator.get(row["pk"], []),
                track_names=track_names,
                facilitator_names=facilitator_names,
                track_pk=track_pk,
            )
            for row in facilitator_rows
        ]
        # What still needs a call goes on top; the rest keeps its name order.
        facilitators.sort(key=lambda f: (f.is_fully_confirmed, f.display_name, f.pk))

        # The strip counts the block, not the facilitators' whole programs.
        in_track = [
            row
            for row in session_rows
            if row["agenda_item_pk"] is not None
            and track_pk in track_names.get(row["session_pk"], {})
        ]
        scheduled = len({row["session_pk"] for row in in_track})
        confirmed = len({row["session_pk"] for row in in_track if row["is_confirmed"]})
        return ConfirmationTrackViewDTO(
            facilitators=facilitators,
            facilitator_count=len(facilitators),
            unclaimed_facilitator_count=sum(
                1 for f in facilitators if f.organizer_id is None
            ),
            scheduled_count=scheduled,
            confirmed_count=confirmed,
            progress_pct=_progress_pct(confirmed=confirmed, scheduled=scheduled),
            without_facilitator_count=orphans,
        )

    def facilitator_card(
        self, *, event_pk: int, track_pk: int, facilitator_pk: int
    ) -> ConfirmationFacilitatorDTO:
        row = self._read_facilitator_in_event(
            event_pk=event_pk, facilitator_pk=facilitator_pk
        )
        # `track_pk` comes from the form, so it gets the same treatment as the
        # facilitator: a block of another event never reaches the render.
        require_track_in_event(
            tracks=self._tracks, track_pk=track_pk, event_pk=event_pk
        )
        sessions = self._sessions.list_confirmation_rows(event_pk, [facilitator_pk])
        session_pks = [session["session_pk"] for session in sessions]
        return _facilitator(
            row=row,
            sessions=sessions,
            track_names=self._sessions.list_track_names_by_session(session_pks),
            facilitator_names=self._sessions.list_facilitator_names_by_session(
                session_pks
            ),
            track_pk=track_pk,
        )

    def set_confirmed(
        self,
        *,
        event_pk: int,
        facilitator_pk: int,
        confirmed: bool,
        contact_email: str | None = None,
        agenda_item_pk: int | None = None,
    ) -> None:
        # Panel access proves this organizer manages the event, not that the
        # ids in the request belong to it — resolve the facilitator inside the
        # event first, so a foreign id cannot reach the update.
        self._read_facilitator_in_event(
            event_pk=event_pk, facilitator_pk=facilitator_pk
        )
        # One UPDATE, so no transaction to open around it.
        matched = self._agenda_items.set_confirmed_for_facilitator(
            event_pk=event_pk,
            facilitator_pk=facilitator_pk,
            confirmed=confirmed,
            contact_email=contact_email,
            agenda_item_pk=agenda_item_pk,
        )
        # Naming one item and hitting nothing means the item is not this
        # facilitator's (or not placed at all) — say so instead of reporting a
        # write that never happened. A scope-wide call legitimately matches none.
        if agenda_item_pk is not None and not matched:
            raise NotFoundError

    def _read_facilitator_in_event(
        self, *, event_pk: int, facilitator_pk: int
    ) -> ConfirmationFacilitatorRow:
        facilitator = self._facilitators.read(facilitator_pk)
        if facilitator.event_id != event_pk:
            raise NotFoundError
        return ConfirmationFacilitatorRow(
            pk=facilitator.pk,
            display_name=facilitator.display_name,
            slug=facilitator.slug,
            organizer_id=facilitator.organizer_id,
            organizer_name=facilitator.organizer_name or "",
        )

    def dashboard(self, event_pk: int) -> ConfirmationDashboardDTO:
        organizer_rows = self._facilitators.count_confirmations_by_organizer(event_pk)
        track_rows = self._agenda_items.count_confirmations_by_track(event_pk)
        manager_names = self._tracks.list_manager_names_by_event(event_pk)
        without_facilitator = self._agenda_items.count_without_facilitator(event_pk)

        # Straight off the items: a session run by two facilitators lands in
        # two organizer rows, so summing those rows would count it twice.
        totals = self._agenda_items.count_event_totals(event_pk)
        scheduled = totals["scheduled_count"]
        confirmed = totals["confirmed_count"]
        return ConfirmationDashboardDTO(
            organizers=[_organizer_row(row) for row in organizer_rows],
            tracks=[
                _track_row(row, manager_names.get(row["key"] or 0, []))
                for row in track_rows
            ],
            scheduled_count=scheduled,
            confirmed_count=confirmed,
            progress_pct=_progress_pct(confirmed=confirmed, scheduled=scheduled),
            claimed_facilitator_count=sum(
                row["facilitator_count"] for row in organizer_rows if row["key"]
            ),
            unclaimed_facilitator_count=sum(
                row["facilitator_count"] for row in organizer_rows if not row["key"]
            ),
            without_facilitator_count=without_facilitator,
        )


def _session_dto(
    *,
    row: ConfirmationSessionRow,
    track_names: dict[int, dict[int, str]],
    facilitator_names: dict[int, dict[int, str]],
    track_pk: int,
) -> ConfirmationSessionDTO:
    others = track_names.get(row["session_pk"], {})
    co_facilitators = facilitator_names.get(row["session_pk"], {})
    return ConfirmationSessionDTO(
        session_pk=row["session_pk"],
        title=row["title"],
        category_name=row["category_name"],
        room_name=row["room_name"],
        start_time=row["start_time"],
        end_time=row["end_time"],
        agenda_item_pk=row["agenda_item_pk"],
        is_confirmed=row["is_confirmed"],
        co_facilitator_names=[
            name for pk, name in co_facilitators.items() if pk != row["facilitator_pk"]
        ],
        other_track_names=[name for pk, name in others.items() if pk != track_pk],
    )


def _status_key(row: ConfirmationSessionRow) -> str:
    # Grouping runs on status alone. Confirmation is a checkbox on the row, so
    # ticking one never moves it into another group.
    if row["agenda_item_pk"] is not None:
        return SCHEDULED_STATUS
    return str(row["status"])


def _email_group(
    *,
    contact_email: str,
    rows: list[ConfirmationSessionRow],
    track_names: dict[int, dict[int, str]],
    facilitator_names: dict[int, dict[int, str]],
    track_pk: int,
) -> ConfirmationEmailGroupDTO:
    by_status: dict[str, list[ConfirmationSessionRow]] = defaultdict(list)
    for row in rows:
        by_status[_status_key(row)].append(row)
    return ConfirmationEmailGroupDTO(
        contact_email=contact_email,
        status_groups=[
            ConfirmationStatusGroupDTO(
                status=status,
                sessions=[
                    _session_dto(
                        row=row,
                        track_names=track_names,
                        facilitator_names=facilitator_names,
                        track_pk=track_pk,
                    )
                    for row in by_status[status]
                ],
            )
            for status in STATUS_ORDER
            if by_status.get(status)
        ],
        confirmable_count=len(by_status.get(SCHEDULED_STATUS, [])),
    )


# A typed key, because a lambda here would be an implicit `Any` parameter.
def _email_sort_key(email: str) -> tuple[bool, str]:
    return (not email, email)


def _facilitator(
    *,
    row: ConfirmationFacilitatorRow,
    sessions: list[ConfirmationSessionRow],
    track_names: dict[int, dict[int, str]],
    facilitator_names: dict[int, dict[int, str]],
    track_pk: int,
) -> ConfirmationFacilitatorDTO:
    # Only a placed session can be confirmed. Accepted-but-unplaced and pending
    # sessions become counts: there is nothing to tick, and pending detail may
    # still change before a decision.
    listed: dict[str, list[ConfirmationSessionRow]] = defaultdict(list)
    counted: Counter[SessionStatus] = Counter()
    for session in sessions:
        if session["agenda_item_pk"] is None and session["status"] in COUNTED_UNPLACED:
            counted[session["status"]] += 1
        else:
            listed[session["contact_email"]].append(session)

    scheduled_count = sum(1 for s in sessions if s["agenda_item_pk"] is not None)
    confirmed_count = sum(1 for s in sessions if s["is_confirmed"])
    return ConfirmationFacilitatorDTO(
        pk=row["pk"],
        display_name=row["display_name"],
        slug=row["slug"],
        organizer_id=row["organizer_id"],
        organizer_name=row["organizer_name"],
        email_groups=[
            _email_group(
                contact_email=email,
                rows=listed[email],
                track_names=track_names,
                facilitator_names=facilitator_names,
                track_pk=track_pk,
            )
            # An address-less group sorts last: it is the one needing a fix,
            # not the one to start reading from.
            for email in sorted(listed, key=_email_sort_key)
        ],
        scheduled_count=scheduled_count,
        confirmed_count=confirmed_count,
        unplaced_count=counted[SessionStatus.ACCEPTED],
        pending_count=counted[SessionStatus.PENDING],
        is_fully_confirmed=bool(scheduled_count) and confirmed_count == scheduled_count,
    )


def _organizer_row(row: ConfirmationCountsRow) -> ConfirmationOrganizerRowDTO:
    return ConfirmationOrganizerRowDTO(
        organizer_id=row["key"],
        organizer_name=row["name"],
        facilitator_count=row["facilitator_count"],
        scheduled_count=row["scheduled_count"],
        confirmed_count=row["confirmed_count"],
        progress_pct=_progress_pct(
            confirmed=row["confirmed_count"], scheduled=row["scheduled_count"]
        ),
    )


def _track_row(
    row: ConfirmationCountsRow, manager_names: list[str]
) -> ConfirmationTrackRowDTO:
    return ConfirmationTrackRowDTO(
        track_pk=row["key"] or 0,
        track_name=row["name"],
        manager_names=manager_names,
        facilitator_count=row["facilitator_count"],
        scheduled_count=row["scheduled_count"],
        confirmed_count=row["confirmed_count"],
        progress_pct=_progress_pct(
            confirmed=row["confirmed_count"], scheduled=row["scheduled_count"]
        ),
    )


class EventPanelService(EventPanelServiceProtocol):
    def __init__(self, events: EventRepositoryProtocol) -> None:
        self._events = events

    def load_context(self, sphere_id: int, slug: str) -> EventPanelContextDTO:
        current_event = self._events.read_by_slug(slug, sphere_id)
        stats_data = self._events.get_stats_data(current_event.pk)
        return EventPanelContextDTO(
            events=self._events.list_by_sphere(sphere_id),
            current_event=current_event,
            is_proposal_active=is_proposal_active(current_event),
            stats=build_panel_stats(stats_data),
        )


class LandingService:
    def __init__(self, stats: LandingStatsRepositoryProtocol) -> None:
        self._stats = stats

    def stats(self) -> LandingStatsDTO:
        return self._stats.count_landing_stats()
