from datetime import UTC, datetime

from ludamus.pacts.event import EventPanelContextDTO, EventPanelServiceProtocol
from ludamus.pacts.legacy import (
    EventDTO,
    EventRepositoryProtocol,
    EventStatsData,
    PanelStatsDTO,
)


def _is_proposal_active(event: EventDTO) -> bool:
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


class EventPanelService(EventPanelServiceProtocol):
    def __init__(self, events: EventRepositoryProtocol) -> None:
        self._events = events

    def load_context(self, sphere_id: int, slug: str) -> EventPanelContextDTO:
        current_event = self._events.read_by_slug(slug, sphere_id)
        stats_data = self._events.get_stats_data(current_event.pk)
        return EventPanelContextDTO(
            events=self._events.list_by_sphere(sphere_id),
            current_event=current_event,
            is_proposal_active=_is_proposal_active(current_event),
            stats=build_panel_stats(stats_data),
        )
