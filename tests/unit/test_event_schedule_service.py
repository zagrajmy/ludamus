"""EventScheduleService: what the public event page reads.

Ways it could go wrong, pinned below: an offered seat marking the viewer as
enrolled; a seat of a companion not marking the session; a closed window's
banner or end-time limit reaching the page; a private or free-text field
offered as a filter; a read scoped to another event than the page's.
"""

from datetime import UTC, datetime, timedelta

from ludamus.mills.event_schedule import EventScheduleService
from ludamus.pacts.enrollment import EnrollmentWindowDTO
from ludamus.pacts.event_page import SeatStatusDTO, ViewerSeatsDTO
from ludamus.pacts.fields import OrganizerFieldDTO
from ludamus.pacts.ids import EventId, SessionId, UserId
from ludamus.pacts.legacy import SessionParticipationStatus

_EVENT = EventId(7)
_NOW = datetime.now(UTC)


class FakeSchedule:
    def __init__(self, seats=()):
        self.seats = list(seats)
        self.reads: list[tuple] = []

    def scheduled_cards(self, *, event_id, roster_up_to):
        self.reads.append(("scheduled", event_id, roster_up_to))
        return []

    def review_queue(self, event_id):
        self.reads.append(("review", event_id))
        return []

    def own_proposals(self, *, event_id, presenter_id):
        self.reads.append(("own", event_id, presenter_id))
        return []

    def seat_statuses(self, *, session_ids, user_ids):
        self.reads.append(("seats", tuple(session_ids), tuple(user_ids)))
        return self.seats


class FakeWindows:
    def __init__(self, windows=()):
        self.windows = list(windows)

    def list_for_event(self, event_id):
        return [window for window in self.windows if window.event_id == event_id]


class FakeSessionFields:
    def __init__(self, fields=()):
        self.fields = list(fields)

    def list_by_event(self, event_id):
        assert event_id == _EVENT
        return self.fields


def _service(*, schedule=None, windows=(), fields=()):
    return EventScheduleService(
        schedule=schedule or FakeSchedule(),
        windows=FakeWindows(windows),
        session_fields=FakeSessionFields(fields),
    )


def _window(pk, *, opened, banner="", limit_to_end_time=False):
    start = _NOW - timedelta(days=1) if opened else _NOW + timedelta(days=1)
    return EnrollmentWindowDTO(
        pk=pk,
        event_id=_EVENT,
        start_time=start,
        end_time=start + timedelta(days=2),
        percentage_slots=100,
        limit_to_end_time=limit_to_end_time,
        banner_text=banner,
        max_waitlist_sessions=0,
        restrict_to_configured_users=False,
        allow_anonymous_enrollment=False,
    )


def _field(pk, *, field_type, is_public):
    return OrganizerFieldDTO(
        field_type=field_type,
        is_public=is_public,
        name=f"Field {pk}",
        order=pk,
        pk=pk,
        question="?",
        slug=f"field-{pk}",
    )


class TestReads:
    def test_each_read_is_scoped_to_the_page_event(self):
        schedule = FakeSchedule()
        service = _service(schedule=schedule)

        service.scheduled_cards(event_id=_EVENT, roster_up_to=20)
        service.review_queue(_EVENT)
        service.own_proposals(event_id=_EVENT, presenter_id=UserId(3))

        assert schedule.reads == [
            ("scheduled", _EVENT, 20),
            ("review", _EVENT),
            ("own", _EVENT, UserId(3)),
        ]


class TestViewerSeats:
    def test_any_of_the_people_marks_the_session(self):
        schedule = FakeSchedule(
            seats=[
                SeatStatusDTO(session_id=1, status=SessionParticipationStatus.WAITING),
                SeatStatusDTO(
                    session_id=1, status=SessionParticipationStatus.CONFIRMED
                ),
                SeatStatusDTO(session_id=2, status=SessionParticipationStatus.WAITING),
            ]
        )

        seats = _service(schedule=schedule).viewer_seats(
            session_ids=[1, 2], user_ids=[10, 11]
        )

        assert seats == {
            SessionId(1): ViewerSeatsDTO(enrolled=True, waiting=True),
            SessionId(2): ViewerSeatsDTO(enrolled=False, waiting=True),
        }

    def test_an_offered_seat_is_neither_enrolled_nor_waiting(self):
        schedule = FakeSchedule(
            seats=[
                SeatStatusDTO(session_id=1, status=SessionParticipationStatus.OFFERED)
            ]
        )

        seats = _service(schedule=schedule).viewer_seats(session_ids=[1], user_ids=[10])

        assert seats == {SessionId(1): ViewerSeatsDTO()}


class TestEnrollmentNotices:
    def test_only_open_windows_speak(self):
        service = _service(
            windows=[
                _window(1, opened=True, banner="Members first"),
                _window(2, opened=True),
                _window(3, opened=False, banner="Later", limit_to_end_time=True),
            ]
        )

        notices = service.enrollment_notices(_EVENT)

        assert notices.banners == ["Members first"]
        assert not notices.limits_to_end_time

    def test_an_open_window_limited_to_its_end_says_so(self):
        service = _service(windows=[_window(1, opened=True, limit_to_end_time=True)])

        assert service.enrollment_notices(_EVENT).limits_to_end_time


def test_public_select_fields_keep_only_public_selects():
    public_select = _field(1, field_type="select", is_public=True)
    service = _service(
        fields=[
            public_select,
            _field(2, field_type="select", is_public=False),
            _field(3, field_type="text", is_public=True),
        ]
    )

    assert service.public_select_fields(_EVENT) == [public_select]
