from contextlib import contextmanager
from datetime import UTC, datetime

import pytest

from ludamus.mills.enrollment import AnonymousEnrollmentService
from ludamus.pacts.crowd import UserDTO, UserType
from ludamus.pacts.enrollment import (
    AnonymousEnrollmentError,
    AnonymousEnrollmentErrorCode,
    AnonymousEnrollmentRequestDTO,
    AnonymousEnrollmentWindowSnapshot,
    AnonymousSeatingDTO,
    AnonymousSessionDTO,
)
from ludamus.pacts.legacy import NotFoundError, SessionParticipationStatus

_SESSION_ID = 42
_EVENT_ID = 7
_SITE_ID = 3
_USER_PK = 11
_CODE = "ab12"


def _open_window(**overrides) -> AnonymousEnrollmentWindowSnapshot:
    values = {"percentage_slots": 100, "allow_anonymous_enrollment": True}
    values.update(overrides)
    return AnonymousEnrollmentWindowSnapshot(**values)


def _seating(**overrides) -> AnonymousSeatingDTO:
    values = {
        "title": "Warsztat",
        "participants_limit": 10,
        "enrolled_count": 0,
        "eligible_windows": [_open_window()],
    }
    values.update(overrides)
    return AnonymousSeatingDTO(**values)


@contextmanager
def _atomic():
    yield


class FakeTransaction:
    @staticmethod
    def atomic():
        return _atomic()


def _user() -> UserDTO:
    return UserDTO(
        avatar_url="",
        date_joined=datetime(2026, 1, 1, tzinfo=UTC),
        discord_username="",
        email="",
        full_name="Ala",
        is_active=False,
        is_authenticated=True,
        is_staff=False,
        is_superuser=False,
        name="Ala",
        pk=_USER_PK,
        slug=f"code_{_CODE}",
        use_gravatar=False,
        user_type=UserType.ANONYMOUS,
        username="anon_x",
    )


def _session_ctx(**overrides) -> AnonymousSessionDTO:
    values = {
        "session_id": _SESSION_ID,
        "event_id": _EVENT_ID,
        "event_slug": "conv",
        "has_agenda_item": True,
        "participants_limit": 10,
        "eligible_windows": [_open_window()],
        "title": "Warsztat",
        "facilitator_name": "Prowadzący",
        "description": "",
        "min_age": 0,
        "enrolled_count": 0,
        "waiting_count": 0,
        "space_name": "Sala A",
        "start_time": datetime(2026, 7, 1, 10, tzinfo=UTC),
        "end_time": datetime(2026, 7, 1, 12, tzinfo=UTC),
    }
    values.update(overrides)
    return AnonymousSessionDTO(**values)


class FakeUsers:
    def __init__(self, user: UserDTO | None):
        self._user = user

    def read(self, slug):
        if self._user is None or self._user.slug != slug:
            raise NotFoundError
        return self._user

    def update(self, slug, user_data):
        pass


class FakeRepo:
    def __init__(self, **cfg):
        # Configured returns: session, participation_status, seating,
        # event_slugs.
        self._cfg = cfg
        self.confirmed: list[tuple[int, int]] = []
        self.waiting: list[tuple[int, int]] = []

    def event_slug_by_id(self, event_id):
        return self._cfg.get("event_slugs", {}).get(event_id)

    def read_session(self, **_kwargs):
        if self._cfg.get("session") is None:
            raise NotFoundError
        return self._cfg["session"]

    def read_participation_status(self, **_kwargs):
        return self._cfg.get("participation_status")

    def has_conflicts(self, **_kwargs):
        return False

    def lock_seating(self, _session_id):
        return self._cfg["seating"]

    def create_or_confirm(self, *, session_id, user_id):
        self.confirmed.append((session_id, user_id))

    def create_waiting(self, *, session_id, user_id):
        self.waiting.append((session_id, user_id))


class FakePromotion:
    def fill_freed_seats(self, *, session_id):
        pass


def _service(
    *, repo: FakeRepo, users: FakeUsers | None = None
) -> AnonymousEnrollmentService:
    return AnonymousEnrollmentService(
        transaction=FakeTransaction(),
        user_repository=users if users is not None else FakeUsers(_user()),
        enrollment_repository=repo,
        waitlist_promotion=FakePromotion(),
    )


def _request(**overrides) -> AnonymousEnrollmentRequestDTO:
    values = {
        "event_slug": "conv",
        "session_id": _SESSION_ID,
        "site_id": _SITE_ID,
        "anonymous_event_id": _EVENT_ID,
        "code": _CODE,
    }
    values.update(overrides)
    return AnonymousEnrollmentRequestDTO(**values)


def _error_code(excinfo) -> AnonymousEnrollmentErrorCode:
    return excinfo.value.code


class TestValidation:
    def test_session_from_other_event(self):
        repo = FakeRepo(
            session=_session_ctx(event_id=_EVENT_ID + 1),
            event_slugs={_EVENT_ID: "conv"},
        )
        service = _service(repo=repo)

        with pytest.raises(AnonymousEnrollmentError) as excinfo:
            service.get_enroll_page(_request())

        assert _error_code(excinfo) == AnonymousEnrollmentErrorCode.NOT_FOR_THIS_SESSION
        assert excinfo.value.event_slug == "conv"

    def test_missing_code_means_expired_session(self):
        service = _service(repo=FakeRepo(session=_session_ctx()))

        with pytest.raises(AnonymousEnrollmentError) as excinfo:
            service.get_enroll_page(_request(code=None))

        assert _error_code(excinfo) == AnonymousEnrollmentErrorCode.SESSION_EXPIRED

    def test_unknown_code(self):
        service = _service(repo=FakeRepo(session=_session_ctx()), users=FakeUsers(None))

        with pytest.raises(AnonymousEnrollmentError) as excinfo:
            service.get_enroll_page(_request())

        assert _error_code(excinfo) == AnonymousEnrollmentErrorCode.USER_NOT_FOUND


class TestGetEnrollPage:
    def test_unscheduled_page_shows_when_already_enrolled(self):
        repo = FakeRepo(
            session=_session_ctx(has_agenda_item=False),
            participation_status=SessionParticipationStatus.CONFIRMED,
            event_slugs={_EVENT_ID: "conv"},
        )
        service = _service(repo=repo)

        page = service.get_enroll_page(_request())

        assert page.enrollment_status == SessionParticipationStatus.CONFIRMED


class TestEnroll:
    def test_rejects_when_enrollment_closes_before_seating_lock(self):
        repo = FakeRepo(session=_session_ctx(), seating=_seating(eligible_windows=[]))
        service = _service(repo=repo)

        with pytest.raises(AnonymousEnrollmentError) as excinfo:
            service.enroll(_request(), "Ala")

        assert _error_code(excinfo) == AnonymousEnrollmentErrorCode.ENROLLMENT_CLOSED
        assert not repo.confirmed
        assert not repo.waiting


class TestLoadByCode:
    def test_unknown_code(self):
        service = _service(repo=FakeRepo(), users=FakeUsers(None))

        with pytest.raises(AnonymousEnrollmentError) as excinfo:
            service.load_by_code(code="nope")

        assert _error_code(excinfo) == AnonymousEnrollmentErrorCode.USER_NOT_FOUND
