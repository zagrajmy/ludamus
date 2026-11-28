from contextlib import nullcontext
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from ludamus.mills.timetable import (
    ConflictDetectionService,
    TimetableOverviewService,
    TimetableService,
)
from ludamus.pacts.availability import AvailabilityDTO, DayPart
from ludamus.pacts.event import EventRepositoryProtocol
from ludamus.pacts.sessions import SessionRepositoryProtocol
from ludamus.pacts.sphere import SphereRepositoryProtocol
from ludamus.pacts.timetable import (
    AgendaItemDTO,
    AgendaItemRepositoryProtocol,
    ScheduleChangeLogRepositoryProtocol,
    TimetableRepos,
)
from ludamus.pacts.tracks import TrackRepositoryProtocol
from ludamus.pacts.venues import SpaceRepositoryProtocol
from tests.unit.factories import event_dto, sphere_dto, track_dto


def spheres_stub(*, require_session_space: bool) -> MagicMock:
    spheres = MagicMock(spec=SphereRepositoryProtocol)
    spheres.read.return_value = sphere_dto(require_session_space=require_session_space)
    return spheres


def _timetable_repos(uow) -> TimetableRepos:
    return TimetableRepos(
        events=uow.events,
        sessions=uow.sessions,
        agenda_items=uow.agenda_items,
        spaces=uow.spaces,
        tracks=uow.tracks,
        schedule_change_logs=uow.schedule_change_logs,
    )


def timetable_service(uow, *, categories=None) -> TimetableService:
    transaction = MagicMock()
    transaction.atomic = uow.atomic
    return TimetableService(
        transaction,
        _timetable_repos(uow),
        categories=categories or MagicMock(),
        spheres=uow.spheres,
    )


def conflict_service(uow) -> ConflictDetectionService:
    return ConflictDetectionService(_timetable_repos(uow))


def overview_service(uow) -> TimetableOverviewService:
    return TimetableOverviewService(_timetable_repos(uow))


def event_stub(start, end, *, pk=1, publication_time=None, auto_confirm=True):
    # The grid reads its days and hours off the event itself, so a stubbed
    # event needs real datetimes rather than a bare MagicMock attribute.
    event = MagicMock()
    event.pk = pk
    event.start_time = start
    event.end_time = end
    event.publication_time = publication_time
    event.auto_confirm_sessions = auto_confirm
    return event


def facilitator_stub(pk, display_name="Alice", *, is_collective=False):
    facilitator = MagicMock()
    facilitator.pk = pk
    facilitator.display_name = display_name
    facilitator.is_collective = is_collective
    return facilitator


def offered(day: int, part: DayPart) -> AvailabilityDTO:
    return AvailabilityDTO(day=date(2026, 1, day), offer=part)


def event_track(*, event_pk):
    track = MagicMock()
    track.event_id = event_pk
    return track


def con_event(**overrides):
    return event_dto(
        **{
            "end_time": END + timedelta(days=1),
            "name": "Con",
            "slug": "con",
            "sphere_id": 3,
            "start_time": START - timedelta(days=1),
            **overrides,
        }
    )


def numbered_track(pk, name="Track"):
    return track_dto(
        creation_time=START,
        modification_time=START,
        name=name,
        pk=pk,
        slug=f"track-{pk}",
    )


def lookup(mapping):
    return mapping.__getitem__


def subset(mapping):
    return lambda pks: {pk: mapping[pk] for pk in mapping.keys() & pks}


def stub_warning_reads(uow):
    uow.sessions.read_facilitators_by_sessions.side_effect = subset({})
    uow.sessions.read_availability_by_sessions.side_effect = subset({})
    uow.sessions.list_track_names_by_session.side_effect = subset({})
    uow.tracks.list_manager_names_by_tracks.side_effect = subset({})


def spec_uow(**repos):
    uow = SimpleNamespace(
        atomic=nullcontext,
        events=MagicMock(spec=EventRepositoryProtocol),
        sessions=MagicMock(spec=SessionRepositoryProtocol),
        agenda_items=MagicMock(spec=AgendaItemRepositoryProtocol),
        spaces=MagicMock(spec=SpaceRepositoryProtocol),
        tracks=MagicMock(spec=TrackRepositoryProtocol),
        schedule_change_logs=MagicMock(spec=ScheduleChangeLogRepositoryProtocol),
        spheres=spheres_stub(require_session_space=True),
    )
    uow.__dict__.update(repos)
    return uow


class FakeAgendaItems:
    def __init__(self, *items):
        self.rows = {item.pk: item for item in items}
        self.event_pk = 1
        self.by_track: dict[int, list[AgendaItemDTO]] = {}
        self.facilitators_by_session: dict[int, set[int]] = {}
        self.created: list[dict] = []
        self.reads: list[tuple[int, set[int] | None]] = []

    def list_by_event(self, event_pk, facilitator_pks=None):
        self.reads.append((event_pk, facilitator_pks))
        return [
            item
            for item in self.rows.values()
            if event_pk == self.event_pk
            and (
                not facilitator_pks
                or self.facilitators_by_session.get(item.session_id, set())
                & facilitator_pks
            )
        ]

    def list_by_track(self, track_pk):
        return list(self.by_track.get(track_pk, []))

    def read_by_session(self, session_pk):
        return next(
            (item for item in self.rows.values() if item.session_id == session_pk), None
        )

    def create(self, data):
        self.created.append(data)

    def delete(self, pk):
        del self.rows[pk]


START = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
END = datetime(2026, 1, 1, 11, 0, tzinfo=UTC)
