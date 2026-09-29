from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from ludamus.mills.enrollment import AnonymousEnrollmentService
from ludamus.pacts.crowd import UserDTO, UserType
from ludamus.pacts.enrollment import (
    AnonymousEnrollmentError,
    AnonymousEnrollmentErrorCode,
    AnonymousEnrollmentRequestDTO,
    AnonymousEnrollmentWindowSnapshot,
    AnonymousEnrollOutcome,
    AnonymousEventDTO,
    AnonymousSeatingDTO,
    AnonymousSessionContextDTO,
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


def _user(name="Ala") -> UserDTO:
    return UserDTO(
        avatar_url="",
        date_joined=datetime(2026, 1, 1, tzinfo=UTC),
        discord_username="",
        email="",
        full_name=name,
        is_active=False,
        is_authenticated=True,
        is_staff=False,
        is_superuser=False,
        name=name,
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
        self.created: list[dict] = []
        self.updated: list[tuple[str, dict]] = []

    def read(self, slug):
        if self._user is None or self._user.slug != slug:
            raise NotFoundError
        return self._user

    def create(self, user_data):
        self.created.append(user_data)

    def update(self, slug, user_data):
        self.updated.append((slug, user_data))


class FakeRepo:
    def __init__(self, **cfg):
        # Configured returns: event, session, participation_status, conflicts,
        # seating, event_slugs.
        self._cfg = cfg
        self.log = SimpleNamespace(
            confirmed=[],
            waiting=[],
            deleted=[],
            events_read=[],
            sessions_read=[],
            statuses_read=[],
            conflicts_checked=[],
            seatings_locked=[],
        )

    def read_event(self, event_slug):
        self.log.events_read.append(event_slug)
        if self._cfg.get("event") is None:
            raise NotFoundError
        return self._cfg["event"]

    def event_slug_by_id(self, event_id):
        return self._cfg.get("event_slugs", {}).get(event_id)

    def read_session(self, **kwargs):
        self.log.sessions_read.append(kwargs)
        if self._cfg.get("session") is None:
            raise NotFoundError
        return self._cfg["session"]

    def read_participation_status(self, **kwargs):
        self.log.statuses_read.append(kwargs)
        return self._cfg.get("participation_status")

    def has_conflicts(self, **kwargs):
        self.log.conflicts_checked.append(kwargs)
        return self._cfg.get("conflicts", False)

    def lock_seating(self, session_id):
        self.log.seatings_locked.append(session_id)
        if (seating := self._cfg.get("seating")) is not None:
            return seating
        participants_limit = 10
        enrolled_count = participants_limit if self._cfg.get("is_full", False) else 0
        return _seating(
            participants_limit=participants_limit, enrolled_count=enrolled_count
        )

    def create_or_confirm(self, *, session_id, user_id):
        self.log.confirmed.append((session_id, user_id))

    def create_waiting(self, *, session_id, user_id):
        self.log.waiting.append((session_id, user_id))

    def delete_participation(self, *, session_id, user_id):
        self.log.deleted.append((session_id, user_id))
        return self._cfg.get("participation_status")


class FakePromotion:
    def __init__(self):
        self.filled: list[int] = []

    def fill_freed_seats(self, *, session_id):
        self.filled.append(session_id)


def _service(
    *,
    repo: FakeRepo,
    users: FakeUsers | None = None,
    promotion: FakePromotion | None = None,
) -> AnonymousEnrollmentService:
    return AnonymousEnrollmentService(
        transaction=FakeTransaction(),
        user_repository=users if users is not None else FakeUsers(_user()),
        enrollment_repository=repo,
        waitlist_promotion=promotion if promotion is not None else FakePromotion(),
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


_CODE_LENGTH = 6


def _error_code(excinfo) -> AnonymousEnrollmentErrorCode:
    return excinfo.value.code


class TestActivate:
    def test_creates_user_and_returns_code(self):
        repo = FakeRepo(
            event=AnonymousEventDTO(
                event_id=_EVENT_ID, slug="conv", active_windows=[_open_window()]
            )
        )
        users = FakeUsers(_user())
        service = _service(repo=repo, users=users)

        activation = service.activate(event_slug="conv")

        assert activation.event_id == _EVENT_ID
        assert activation.event_slug == "conv"
        assert repo.log.events_read == ["conv"]
        assert len(users.created) == 1
        created = users.created[0]
        assert created["slug"] == f"code_{activation.code}"
        assert not created["name"]
        assert created["user_type"] == UserType.ANONYMOUS
        assert created["is_active"] is False
        assert created["username"].startswith("anon_")
        assert created["username"] == created["username"].lower()
        assert activation.code == activation.code.lower()
        assert len(activation.code) == _CODE_LENGTH


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
    def test_returns_page(self):
        session = _session_ctx()
        repo = FakeRepo(session=session, participation_status=None)
        service = _service(repo=repo, users=FakeUsers(_user(name="")))

        page = service.get_enroll_page(_request())

        assert page.session == AnonymousSessionContextDTO.from_session(
            session=session,
            allows_anonymous_enrollment=True,
            effective_participants_limit=10,
        )
        assert page.anonymous_code == _CODE
        assert page.needs_user_data is True
        assert page.enrollment_status is None
        assert page.is_enrolled is False
        assert repo.log.sessions_read == [
            {"session_id": _SESSION_ID, "event_slug": "conv", "site_id": _SITE_ID}
        ]
        assert repo.log.statuses_read == [
            {"session_id": _SESSION_ID, "user_id": _USER_PK}
        ]

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
    def test_confirms_when_free_seats(self):
        repo = FakeRepo(session=_session_ctx(), is_full=False)
        users = FakeUsers(_user())
        service = _service(repo=repo, users=users)

        result = service.enroll(_request(), "Ala")

        assert result.outcome == AnonymousEnrollOutcome.ENROLLED
        assert result.session_title == "Warsztat"
        assert result.event_slug == "conv"
        assert repo.log.conflicts_checked == [
            {"session_id": _SESSION_ID, "user": _user()}
        ]
        assert repo.log.seatings_locked == [_SESSION_ID]
        assert repo.log.confirmed == [(_SESSION_ID, _USER_PK)]
        assert not repo.log.waiting
        assert users.updated == [(f"code_{_CODE}", {"name": "Ala"})]

    def test_waitlists_when_full(self):
        repo = FakeRepo(session=_session_ctx(), is_full=True)
        service = _service(repo=repo)

        result = service.enroll(_request(), "Ala")

        assert result.outcome == AnonymousEnrollOutcome.WAITLISTED
        assert repo.log.waiting == [(_SESSION_ID, _USER_PK)]
        assert not repo.log.confirmed

    def test_rejects_when_enrollment_closes_before_seating_lock(self):
        repo = FakeRepo(session=_session_ctx(), seating=_seating(eligible_windows=[]))
        service = _service(repo=repo)

        with pytest.raises(AnonymousEnrollmentError) as excinfo:
            service.enroll(_request(), "Ala")

        assert _error_code(excinfo) == AnonymousEnrollmentErrorCode.ENROLLMENT_CLOSED
        assert not repo.log.confirmed
        assert not repo.log.waiting

    def test_conflict_short_circuits(self):
        repo = FakeRepo(session=_session_ctx(), conflicts=True)
        service = _service(repo=repo)

        result = service.enroll(_request(), "Ala")

        assert result.outcome == AnonymousEnrollOutcome.CONFLICT
        assert not repo.log.confirmed
        assert not repo.log.waiting


class TestCancel:
    def test_cancel_frees_seat_and_promotes(self):
        repo = FakeRepo(
            session=_session_ctx(),
            participation_status=SessionParticipationStatus.CONFIRMED,
        )
        promotion = FakePromotion()
        service = _service(repo=repo, promotion=promotion)

        result = service.cancel(_request(), "Ala")

        assert result.cancelled is True
        assert result.session_title == "Warsztat"
        assert repo.log.deleted == [(_SESSION_ID, _USER_PK)]
        assert promotion.filled == [_SESSION_ID]

    def test_cancel_after_agenda_item_removed(self):
        repo = FakeRepo(
            session=_session_ctx(has_agenda_item=False),
            participation_status=SessionParticipationStatus.CONFIRMED,
            event_slugs={_EVENT_ID: "conv"},
        )
        service = _service(repo=repo)

        result = service.cancel(_request(), "Ala")

        assert result.cancelled is True
        assert repo.log.deleted == [(_SESSION_ID, _USER_PK)]


class TestLoadByCode:
    def test_unknown_code(self):
        service = _service(repo=FakeRepo(), users=FakeUsers(None))

        with pytest.raises(AnonymousEnrollmentError) as excinfo:
            service.load_by_code(code="nope")

        assert _error_code(excinfo) == AnonymousEnrollmentErrorCode.USER_NOT_FOUND
