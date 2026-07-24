from datetime import UTC, datetime, timedelta

from ludamus.mills.event import EventPanelService
from ludamus.pacts.legacy import (
    EventDTO,
    EventListItemDTO,
    EventRepositoryProtocol,
    EventStatsData,
    EventUpdateData,
)

_CURRENT_EVENT_ID = 3
_TOTAL_SESSIONS = 7
_TOTAL_PROPOSALS = 8
_HOSTS_COUNT = 3
_ROOMS_COUNT = 4


def _event(*, pk: int = _CURRENT_EVENT_ID, slug: str = "frostfire-con") -> EventDTO:
    current_time = datetime.now(tz=UTC)
    return EventDTO(
        description="",
        end_time=current_time + timedelta(days=2),
        name="Frostfire Con",
        pk=pk,
        proposal_end_time=current_time + timedelta(days=1),
        proposal_start_time=current_time - timedelta(days=1),
        publication_time=current_time - timedelta(days=2),
        slug=slug,
        sphere_id=7,
        start_time=current_time + timedelta(days=1),
    )


def _events() -> list[EventDTO]:
    return [_event(), _event(pk=4, slug="other-event")]


class FakeEvents(EventRepositoryProtocol):
    @staticmethod
    def list_by_sphere(sphere_id: int) -> list[EventDTO]:
        return [event for event in _events() if event.sphere_id == sphere_id]

    @staticmethod
    def list_for_events_page(
        sphere_id: int, *, include_unpublished: bool
    ) -> list[EventListItemDTO]:
        raise NotImplementedError

    @staticmethod
    def read(pk: int) -> EventDTO:
        raise NotImplementedError

    @staticmethod
    def read_by_slug(slug: str, sphere_id: int) -> EventDTO:
        return next(
            event
            for event in _events()
            if event.slug == slug and event.sphere_id == sphere_id
        )

    @staticmethod
    def get_stats_data(event_id: int) -> EventStatsData:
        assert event_id == _CURRENT_EVENT_ID
        return EventStatsData(
            pending_proposals=2,
            scheduled_sessions=5,
            total_proposals=8,
            unique_host_ids={11, 12, 13},
            rooms_count=4,
        )

    @staticmethod
    def update(event_id: int, data: EventUpdateData) -> None:
        raise NotImplementedError


def test_loads_event_panel_context() -> None:
    context = EventPanelService(FakeEvents()).load_context(7, "frostfire-con")

    assert context.current_event.pk == _CURRENT_EVENT_ID
    assert [event.pk for event in context.events] == [_CURRENT_EVENT_ID, 4]
    assert context.is_proposal_active is True
    assert context.stats.total_sessions == _TOTAL_SESSIONS
    assert context.stats.total_proposals == _TOTAL_PROPOSALS
    assert context.stats.hosts_count == _HOSTS_COUNT
    assert context.stats.rooms_count == _ROOMS_COUNT
