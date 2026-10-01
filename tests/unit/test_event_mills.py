import logging
from datetime import UTC, datetime, timedelta

import pytest

from ludamus.mills.event import (
    LANDING_CACHE_SECONDS,
    EventPanelService,
    EventsService,
    LandingService,
    build_panel_stats,
    require_session_in_event,
    require_track_in_event,
    widen_event_dates,
)
from ludamus.pacts.event import (
    EventCreateData,
    EventDatesInvalidError,
    EventPublicationInvalidError,
    EventSlugConflictError,
    LandingConventionDTO,
    LandingStatsDTO,
)
from ludamus.pacts.legacy import (
    EventDTO,
    EventStatsData,
    EventUpdateData,
    NotFoundError,
    TrackDTO,
)
from ludamus.pacts.services import DatabaseConstraintError
from tests.unit.factories import FakeTransaction, event_dto, track_dto

SPHERE = 10
OTHER_SPHERE = 11
EVENT = 1
OTHER_EVENT = 2
_NOW = datetime(2026, 5, 1, 12, tzinfo=UTC)
_START = datetime(2026, 8, 1, 10, tzinfo=UTC)
_END = datetime(2026, 8, 3, 18, tzinfo=UTC)
_PUBLISHED = datetime(2026, 7, 1, tzinfo=UTC)
_EXPECTED_SESSIONS = 7
_EXPECTED_PROPOSALS = 8
_EXPECTED_STATS = LandingStatsDTO(events=3, sessions=40)
_FRESH_STATS = LandingStatsDTO(events=4, sessions=41)


def _event(
    *,
    pk: int = EVENT,
    slug: str = "conf",
    sphere_id: int = SPHERE,
    start: datetime = _START,
    end: datetime = _END,
    publication: datetime | None = _PUBLISHED,
) -> EventDTO:
    return event_dto(
        end_time=end,
        name="Conf",
        pk=pk,
        publication_time=publication,
        slug=slug,
        sphere_id=sphere_id,
        start_time=start,
    )


def _track(*, pk: int, event_id: int) -> TrackDTO:
    return track_dto(
        creation_time=_NOW,
        event_id=event_id,
        modification_time=_NOW,
        name="Block",
        pk=pk,
        slug="block",
    )


class FakeEvents:
    def __init__(self, events: list[EventDTO], *, conflict: bool = False) -> None:
        self.rows = {event.pk: event for event in events}
        self.locked: list[int] = []
        self._conflict = conflict

    def lock(self, pk: int) -> None:
        self.locked.append(pk)

    def read(self, pk: int) -> EventDTO:
        return self.rows[pk]

    def update(self, pk: int, data: EventUpdateData) -> EventDTO:
        self.rows[pk] = self.rows[pk].model_copy(update=dict(data))
        return self.rows[pk]

    def read_by_slug(self, slug: str, sphere_id: int) -> EventDTO:
        return self._one(lambda e: e.slug == slug and e.sphere_id == sphere_id)

    def read_in_sphere(self, pk: int, sphere_id: int) -> EventDTO:
        return self._one(lambda e: e.pk == pk and e.sphere_id == sphere_id)

    def list_by_sphere(self, sphere_id: int) -> list[EventDTO]:
        return [e for e in self.rows.values() if e.sphere_id == sphere_id]

    def list_for_events_page(
        self, sphere_id: int, *, include_unpublished: bool
    ) -> list[EventDTO]:
        return [
            e
            for e in self.list_by_sphere(sphere_id)
            if include_unpublished or e.publication_time is not None
        ]

    @staticmethod
    def get_stats_data(_pk: int) -> EventStatsData:
        return EventStatsData(
            pending_proposals=3,
            scheduled_sessions=4,
            total_proposals=9,
            hosts_count=5,
            rooms_count=2,
        )

    def slug_exists(self, sphere_id: int, slug: str) -> bool:
        return any(
            e.slug == slug and e.sphere_id == sphere_id for e in self.rows.values()
        )

    def create(self, sphere_id: int, data: EventCreateData) -> EventDTO:
        if self._conflict:
            raise DatabaseConstraintError("duplicate key")
        event = _event(
            pk=max(self.rows, default=0) + 1,
            slug=data["slug"],
            sphere_id=sphere_id,
            start=data["start_time"],
            end=data["end_time"],
            publication=data["publication_time"],
        )
        self.rows[event.pk] = event
        return event

    def _one(self, predicate) -> EventDTO:
        for event in self.rows.values():
            if predicate(event):
                return event
        raise NotFoundError


class FakeSessions:
    def __init__(self, event_by_session: dict[int, EventDTO]) -> None:
        self._events = event_by_session

    def read_event(self, session_pk: int) -> EventDTO:
        return self._events[session_pk]


class FakeTracks:
    def __init__(self, tracks: list[TrackDTO]) -> None:
        self._rows = {track.pk: track for track in tracks}

    def read(self, pk: int) -> TrackDTO:
        return self._rows[pk]


class FakeSpheres:
    def __init__(self, pks: set[int]) -> None:
        self._pks = pks

    def read(self, pk: int) -> object:
        if pk not in self._pks:
            raise NotFoundError
        return object()


class FakeSpaces:
    def __init__(self) -> None:
        self.default_for: list[int] = []
        self.filled: set[int] = set()

    def create_default(self, event_pk: int) -> None:
        self.default_for.append(event_pk)

    def list_tree(self, event_pk: int) -> list[object]:
        return [object()] if event_pk in self.filled else []


class FakeSetup:
    def __init__(self, spaces: FakeSpaces) -> None:
        self._spaces = spaces
        self.copies: list[tuple[int, int, datetime]] = []

    def copy(self, *, source_id: int, target_id: int, start_time: datetime) -> None:
        self.copies.append((source_id, target_id, start_time))
        self._spaces.filled.add(target_id)


class FakeCache:
    def __init__(self, entries: dict[str, object] | None = None) -> None:
        self.entries = dict(entries or {})
        self.timeouts: dict[str, int | None] = {}

    def get(self, key: str) -> object:
        return self.entries.get(key)

    def set(self, key: str, value: object, timeout: int | None = None) -> None:
        self.entries[key] = value
        self.timeouts[key] = timeout


class FakeLandingStats:
    def __init__(self, stats: LandingStatsDTO) -> None:
        self._stats = stats
        self.conventions = {
            "a.example": LandingConventionDTO(
                name="A", domain="a.example", event_slug="a-1", cover_image_url=""
            ),
            "b.example": LandingConventionDTO(
                name="B", domain="b.example", event_slug="b-1", cover_image_url=""
            ),
        }

    def count_landing_stats(self) -> LandingStatsDTO:
        return self._stats

    def list_conventions(self, domains: tuple[str, ...]) -> list[LandingConventionDTO]:
        return [self.conventions[domain] for domain in domains]

    @staticmethod
    def read_newest_published_slug(sphere_id: int) -> str | None:
        return "newest" if sphere_id == SPHERE else None


class TestRequireInEvent:
    def test_a_session_of_another_event_is_not_found(self):
        sessions = FakeSessions({5: _event(pk=OTHER_EVENT)})

        with pytest.raises(NotFoundError):
            require_session_in_event(sessions=sessions, session_pk=5, event_pk=EVENT)

    def test_a_session_of_the_event_passes(self):
        sessions = FakeSessions({5: _event(pk=EVENT)})

        assert (
            require_session_in_event(sessions=sessions, session_pk=5, event_pk=EVENT)
            is None
        )

    def test_a_track_of_another_event_is_not_found(self):
        tracks = FakeTracks([_track(pk=3, event_id=OTHER_EVENT)])

        with pytest.raises(NotFoundError):
            require_track_in_event(tracks=tracks, track_pk=3, event_pk=EVENT)

    def test_a_track_of_the_event_passes(self):
        tracks = FakeTracks([_track(pk=3, event_id=EVENT)])

        assert require_track_in_event(tracks=tracks, track_pk=3, event_pk=EVENT) is None


class TestWidenEventDates:
    def test_a_range_inside_the_event_changes_nothing(self):
        events = FakeEvents([_event()])

        grew = widen_event_dates(
            events=events,
            event_pk=EVENT,
            start=datetime(2026, 8, 2, tzinfo=UTC),
            end=datetime(2026, 8, 2, 12, tzinfo=UTC),
        )

        assert grew is False
        assert events.rows[EVENT].start_time == _START
        assert events.rows[EVENT].end_time == _END
        assert events.locked == [EVENT]

    def test_an_earlier_start_moves_the_start_only(self):
        events = FakeEvents([_event()])
        earlier = datetime(2026, 7, 31, 20, tzinfo=UTC)

        grew = widen_event_dates(events=events, event_pk=EVENT, start=earlier, end=_END)

        assert grew is True
        assert events.rows[EVENT].start_time == earlier
        assert events.rows[EVENT].end_time == _END

    def test_a_later_end_moves_the_end_only(self):
        events = FakeEvents([_event()])
        later = datetime(2026, 8, 4, tzinfo=UTC)

        grew = widen_event_dates(events=events, event_pk=EVENT, start=_START, end=later)

        assert grew is True
        assert events.rows[EVENT].start_time == _START
        assert events.rows[EVENT].end_time == later

    def test_a_start_before_publication_is_refused(self):
        events = FakeEvents([_event()])

        with pytest.raises(EventPublicationInvalidError):
            widen_event_dates(
                events=events,
                event_pk=EVENT,
                start=datetime(2026, 6, 30, tzinfo=UTC),
                end=_END,
            )

        assert events.rows[EVENT].start_time == _START

    def test_an_unpublished_event_can_start_any_time_earlier(self):
        events = FakeEvents([_event(publication=None)])
        earlier = datetime(2026, 1, 1, tzinfo=UTC)

        grew = widen_event_dates(events=events, event_pk=EVENT, start=earlier, end=_END)

        assert grew is True
        assert events.rows[EVENT].start_time == earlier


class TestEventPanelService:
    def test_context_carries_sphere_events_and_derived_stats(self):
        events = FakeEvents([_event(), _event(pk=OTHER_EVENT, slug="other")])
        events.rows[3] = _event(pk=3, slug="foreign", sphere_id=OTHER_SPHERE)

        context = EventPanelService(events).load_context(SPHERE, "conf")

        assert context.current_event.pk == EVENT
        assert [e.pk for e in context.events] == [EVENT, OTHER_EVENT]
        assert context.is_proposal_active is False
        assert context.stats.total_sessions == _EXPECTED_SESSIONS
        assert context.stats.hosts_count == FakeEvents.get_stats_data(EVENT).hosts_count

    def test_panel_stats_total_is_pending_plus_scheduled(self):
        stats = build_panel_stats(
            EventStatsData(
                pending_proposals=2,
                scheduled_sessions=5,
                total_proposals=8,
                hosts_count=1,
                rooms_count=1,
            )
        )

        assert stats.total_sessions == _EXPECTED_SESSIONS
        assert stats.total_proposals == _EXPECTED_PROPOSALS


def _landing(cache: FakeCache, stats: LandingStatsDTO = _FRESH_STATS) -> LandingService:
    return LandingService(
        FakeLandingStats(stats),
        cache=cache,
        convention_domains=("b.example", "a.example"),
    )


class TestLandingService:
    def test_a_miss_loads_and_stores_json_for_two_hours(self):
        cache = FakeCache()

        stats = _landing(cache).stats()

        assert stats == _FRESH_STATS
        assert LandingStatsDTO.model_validate_json(cache.entries["landing:stats"]) == (
            _FRESH_STATS
        )
        assert cache.timeouts["landing:stats"] == LANDING_CACHE_SECONDS

    def test_a_valid_entry_is_served_without_reloading(self):
        cache = FakeCache({"landing:stats": _EXPECTED_STATS.model_dump_json()})

        assert _landing(cache).stats() == _EXPECTED_STATS

    def test_a_malformed_entry_is_discarded_and_reloaded(self, caplog):
        cache = FakeCache({"landing:stats": b'{"events": "many"}'})

        with caplog.at_level(logging.WARNING):
            stats = _landing(cache).stats()

        assert stats == _FRESH_STATS
        assert "landing:stats" in caplog.text
        assert LandingStatsDTO.model_validate_json(cache.entries["landing:stats"]) == (
            _FRESH_STATS
        )

    def test_conventions_follow_the_configured_domain_order(self):
        cache = FakeCache()

        conventions = _landing(cache).conventions()

        assert [c.domain for c in conventions] == ["b.example", "a.example"]
        assert "landing:conventions" in cache.entries

    def test_showcase_slug_is_the_newest_published_one(self):
        service = _landing(FakeCache())

        assert service.showcase_slug(SPHERE) == "newest"
        assert service.showcase_slug(OTHER_SPHERE) is None


def _create_data(
    *,
    slug: str = "new-conf",
    start: datetime = _START,
    end: datetime = _END,
    publication: datetime | None = _PUBLISHED,
) -> EventCreateData:
    return EventCreateData(
        name="New",
        slug=slug,
        description="",
        start_time=start,
        end_time=end,
        publication_time=publication,
        auto_confirm_sessions=False,
    )


def _events_service(
    events: FakeEvents,
    *,
    spaces: FakeSpaces | None = None,
    setup: FakeSetup | None = None,
) -> EventsService:
    spaces = spaces or FakeSpaces()
    return EventsService(
        transaction=FakeTransaction(),
        events=events,
        spheres=FakeSpheres({SPHERE}),
        spaces=spaces,
        setup=setup or FakeSetup(spaces),
    )


class TestEventsService:
    def test_listing_hides_unpublished_events_unless_asked(self):
        events = FakeEvents(
            [_event(), _event(pk=OTHER_EVENT, slug="d", publication=None)]
        )
        service = _events_service(events)

        assert [
            e.pk for e in service.list_for_sphere(SPHERE, include_unpublished=False)
        ] == [EVENT]
        assert [
            e.pk for e in service.list_for_sphere(SPHERE, include_unpublished=True)
        ] == [EVENT, OTHER_EVENT]

    def test_reads_are_scoped_to_the_sphere(self):
        service = _events_service(FakeEvents([_event()]))

        assert service.read_by_slug(SPHERE, "conf").pk == EVENT
        assert service.require_in_sphere(sphere_id=SPHERE, event_id=EVENT).pk == EVENT
        with pytest.raises(NotFoundError):
            service.read_by_slug(OTHER_SPHERE, "conf")
        with pytest.raises(NotFoundError):
            service.require_in_sphere(sphere_id=OTHER_SPHERE, event_id=EVENT)

    def test_create_stores_the_event_and_gives_it_a_default_space(self):
        events = FakeEvents([_event()])
        spaces = FakeSpaces()

        created = _events_service(events, spaces=spaces).create(
            sphere_id=SPHERE, data=_create_data()
        )

        assert events.rows[created.pk].slug == "new-conf"
        assert spaces.default_for == [created.pk]

    def test_create_based_on_an_event_copies_its_setup_to_the_new_start(self):
        year = timedelta(days=365)
        events = FakeEvents([_event(start=_START - year, end=_END - year)])
        spaces = FakeSpaces()
        setup = FakeSetup(spaces)

        created = _events_service(events, spaces=spaces, setup=setup).create(
            sphere_id=SPHERE, data=_create_data(), based_on_id=EVENT
        )

        assert setup.copies == [(EVENT, created.pk, _START)]
        assert not spaces.default_for

    def test_create_based_on_another_spheres_event_creates_nothing(self):
        events = FakeEvents([_event(sphere_id=OTHER_SPHERE)])
        spaces = FakeSpaces()
        setup = FakeSetup(spaces)

        with pytest.raises(NotFoundError):
            _events_service(events, spaces=spaces, setup=setup).create(
                sphere_id=SPHERE, data=_create_data(), based_on_id=EVENT
            )

        assert list(events.rows) == [EVENT]
        assert not setup.copies

    def test_create_without_a_slug_derives_a_free_one_from_the_name(self):
        events = FakeEvents([_event(slug="new")])

        created = _events_service(events).create(
            sphere_id=SPHERE, data=_create_data(slug="")
        )

        assert created.slug.startswith("new-")
        assert created.slug != "new"

    def test_create_refuses_an_end_not_after_the_start(self):
        events = FakeEvents([])

        with pytest.raises(EventDatesInvalidError):
            _events_service(events).create(
                sphere_id=SPHERE, data=_create_data(start=_START, end=_START)
            )

        assert events.rows == {}

    def test_create_refuses_publication_after_the_start(self):
        events = FakeEvents([])

        with pytest.raises(EventPublicationInvalidError):
            _events_service(events).create(
                sphere_id=SPHERE,
                data=_create_data(publication=datetime(2026, 8, 2, tzinfo=UTC)),
            )

        assert events.rows == {}

    def test_create_in_an_unknown_sphere_is_not_found(self):
        spaces = FakeSpaces()

        with pytest.raises(NotFoundError):
            _events_service(FakeEvents([]), spaces=spaces).create(
                sphere_id=OTHER_SPHERE, data=_create_data()
            )

        assert not spaces.default_for

    def test_a_taken_slug_is_reported_as_a_slug_conflict(self):
        events = FakeEvents([_event()], conflict=True)
        spaces = FakeSpaces()

        with pytest.raises(EventSlugConflictError) as exc_info:
            _events_service(events, spaces=spaces).create(
                sphere_id=SPHERE, data=_create_data(slug="conf")
            )

        assert isinstance(exc_info.value.__cause__, DatabaseConstraintError)
        assert not spaces.default_for

    def test_another_constraint_violation_keeps_its_own_error(self):
        events = FakeEvents([_event()], conflict=True)

        with pytest.raises(DatabaseConstraintError):
            _events_service(events).create(sphere_id=SPHERE, data=_create_data())
