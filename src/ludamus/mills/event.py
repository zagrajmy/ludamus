from datetime import UTC, datetime

from ludamus.pacts.event import (
    ConfirmationDashboardDTO,
    ConfirmationOrganizerRowDTO,
    ConfirmationTrackRowDTO,
    EventConfirmationsServiceProtocol,
    EventPanelContextDTO,
    EventPanelServiceProtocol,
)
from ludamus.pacts.legacy import (
    AgendaItemRepositoryProtocol,
    ConfirmationCountsRow,
    EventDTO,
    EventRepositoryProtocol,
    EventStatsData,
    FacilitatorRepositoryProtocol,
    PanelStatsDTO,
    TrackRepositoryProtocol,
)


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
        hosts_count=len(stats_data.unique_host_ids),
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
    ) -> None:
        self._facilitators = facilitators
        self._agenda_items = agenda_items
        self._tracks = tracks

    def dashboard(self, event_pk: int) -> ConfirmationDashboardDTO:
        organizer_rows = self._facilitators.count_confirmations_by_organizer(event_pk)
        track_rows = self._agenda_items.count_confirmations_by_track(event_pk)
        manager_names = self._tracks.list_manager_names_by_event(event_pk)
        without_facilitator = self._agenda_items.count_without_facilitator(event_pk)

        # Organizer rows partition the event's facilitators, so their scheduled
        # counts sum to the event total without double counting.
        scheduled = sum(row["scheduled_count"] for row in organizer_rows)
        confirmed = sum(row["confirmed_count"] for row in organizer_rows)
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
