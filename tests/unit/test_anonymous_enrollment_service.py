from contextlib import contextmanager
from datetime import UTC, datetime

import pytest

from ludamus.mills.enrollment import AnonymousEnrollmentService
from ludamus.pacts.crowd import UserDTO, UserType
from ludamus.pacts.enrollment import (
    AnonymousEnrollmentError,
    AnonymousEnrollmentErrorCode,
    AnonymousEnrollmentRequestDTO,
    AnonymousEnrollOutcome,
    AnonymousEventDTO,
    AnonymousLoadDTO,
    AnonymousSeatingDTO,
    AnonymousSessionContextDTO,
)
from ludamus.pacts.legacy import NotFoundError, SessionParticipationStatus

_SESSION_ID = 42
_EVENT_ID = 7
_SITE_ID = 3
_USER_PK = 11
_CODE = "ab12"


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


def _session_ctx(**overrides) -> AnonymousSessionContextDTO:
    values = {
        "session_id": _SESSION_ID,
        "event_id": _EVENT_ID,
        "event_slug": "conv",
        "has_agenda_item": True,
        "allows_anonymous_enrollment": True,
        "title": "Warsztat",
        "display_name": "Prowadzący",
        "description": "",
        "min_age": 0,
        "enrolled_count": 0,
        "waiting_count": 0,
        "effective_participants_limit": 10,
        "space_name": "Sala A",
        "start_time": datetime(2026, 7, 1, 10, tzinfo=UTC),
        "end_time": datetime(2026, 7, 1, 12, tzinfo=UTC),
    }
    values.update(overrides)
    return AnonymousSessionContextDTO(**values)


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
        # is_full, load, event_slugs.
        self._cfg = cfg
        self.confirmed: list[tuple[int, int]] = []
        self.waiting: list[tuple[int, int]] = []
        self.deleted: list[tuple[int, int]] = []

    def read_event(self, _event_slug):
        if self._cfg.get("event") is None:
            raise NotFoundError
        return self._cfg["event"]

    def event_slug_by_id(self, event_id):
        return self._cfg.get("event_slugs", {}).get(event_id)

    def read_session(self, **_kwargs):
        if self._cfg.get("session") is None:
            raise NotFoundError
        return self._cfg["session"]

    def read_participation_status(self, **_kwargs):
        return self._cfg.get("participation_status")

    def has_conflicts(self, **_kwargs):
        return self._cfg.get("conflicts", False)

    def lock_seating(self, _session_id):
        return AnonymousSeatingDTO(
            is_full=self._cfg.get("is_full", False), title="Warsztat"
        )

    def create_or_confirm(self, *, session_id, user_id):
        self.confirmed.append((session_id, user_id))

    def create_waiting(self, *, session_id, user_id):
        self.waiting.append((session_id, user_id))

    def delete_participation(self, *, session_id, user_id):
        self.deleted.append((session_id, user_id))
        return self._cfg.get("participation_status")

    def first_enrollment_event(self, _user_id):
        return self._cfg.get("load")


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


def _error_code(excinfo) -> AnonymousEnrollmentErrorCode:
    return excinfo.value.code


class TestActivate:
    def test_creates_user_and_returns_code(self):
        repo = FakeRepo(
            event=AnonymousEventDTO(
                event_id=_EVENT_ID, slug="conv", allows_anonymous_enrollment=True
            )
        )
        users = FakeUsers(_user())
        service = _service(repo=repo, users=users)

        activation = service.activate(event_slug="conv")

        assert activation.event_id == _EVENT_ID
        assert activation.event_slug == "conv"
        assert len(users.created) == 1
        assert users.created[0]["slug"] == f"code_{activation.code}"
        assert users.created[0]["user_type"] == UserType.ANONYMOUS

    def test_event_not_found(self):
        service = _service(repo=FakeRepo(event=None))

        with pytest.raises(AnonymousEnrollmentError) as excinfo:
            service.activate(event_slug="missing")

        assert _error_code(excinfo) == AnonymousEnrollmentErrorCode.EVENT_NOT_FOUND

    def test_event_disallows_anonymous(self):
        repo = FakeRepo(
            event=AnonymousEventDTO(
                event_id=_EVENT_ID, slug="conv", allows_anonymous_enrollment=False
            )
        )
        service = _service(repo=repo)

        with pytest.raises(AnonymousEnrollmentError) as excinfo:
            service.activate(event_slug="conv")

        assert (
            _error_code(excinfo) == AnonymousEnrollmentErrorCode.NOT_AVAILABLE_FOR_EVENT
        )
        assert excinfo.value.event_slug == "conv"


class TestValidation:
    def test_session_not_found(self):
        service = _service(repo=FakeRepo(session=None))

        with pytest.raises(AnonymousEnrollmentError) as excinfo:
            service.get_enroll_page(_request())

        assert _error_code(excinfo) == AnonymousEnrollmentErrorCode.SESSION_NOT_FOUND

    def test_no_agenda_item_redirects_to_activated_event(self):
        repo = FakeRepo(
            session=_session_ctx(has_agenda_item=False), event_slugs={_EVENT_ID: "conv"}
        )
        service = _service(repo=repo)

        with pytest.raises(AnonymousEnrollmentError) as excinfo:
            service.get_enroll_page(_request())

        assert _error_code(excinfo) == AnonymousEnrollmentErrorCode.NO_ENROLLMENT_CONFIG
        assert excinfo.value.event_slug == "conv"

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

    def test_enrollment_closed_on_enroll(self):
        repo = FakeRepo(session=_session_ctx(allows_anonymous_enrollment=False))
        service = _service(repo=repo)

        with pytest.raises(AnonymousEnrollmentError) as excinfo:
            service.enroll(_request(), "Ala")

        assert _error_code(excinfo) == AnonymousEnrollmentErrorCode.ENROLLMENT_CLOSED
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

        assert page.session == session
        assert page.anonymous_code == _CODE
        assert page.needs_user_data is True
        assert page.enrollment_status is None
        assert page.is_enrolled is False

    def test_closed_enrollment_still_shows_existing_enrollment(self):
        repo = FakeRepo(
            session=_session_ctx(allows_anonymous_enrollment=False),
            participation_status=SessionParticipationStatus.WAITING,
        )
        service = _service(repo=repo)

        page = service.get_enroll_page(_request())

        assert page.enrollment_status == SessionParticipationStatus.WAITING
        assert page.is_enrolled is True

    def test_closed_enrollment_without_enrollment_raises(self):
        repo = FakeRepo(
            session=_session_ctx(allows_anonymous_enrollment=False),
            participation_status=None,
        )
        service = _service(repo=repo)

        with pytest.raises(AnonymousEnrollmentError) as excinfo:
            service.get_enroll_page(_request())

        assert _error_code(excinfo) == AnonymousEnrollmentErrorCode.ENROLLMENT_CLOSED


class TestEnroll:
    def test_confirms_when_free_seats(self):
        repo = FakeRepo(session=_session_ctx(), is_full=False)
        users = FakeUsers(_user())
        service = _service(repo=repo, users=users)

        result = service.enroll(_request(), "Ala")

        assert result.outcome == AnonymousEnrollOutcome.ENROLLED
        assert result.session_title == "Warsztat"
        assert result.event_slug == "conv"
        assert repo.confirmed == [(_SESSION_ID, _USER_PK)]
        assert not repo.waiting
        assert users.updated == [(f"code_{_CODE}", {"name": "Ala"})]

    def test_waitlists_when_full(self):
        repo = FakeRepo(session=_session_ctx(), is_full=True)
        service = _service(repo=repo)

        result = service.enroll(_request(), "Ala")

        assert result.outcome == AnonymousEnrollOutcome.WAITLISTED
        assert repo.waiting == [(_SESSION_ID, _USER_PK)]
        assert not repo.confirmed

    def test_conflict_short_circuits(self):
        repo = FakeRepo(session=_session_ctx(), conflicts=True)
        service = _service(repo=repo)

        result = service.enroll(_request(), "Ala")

        assert result.outcome == AnonymousEnrollOutcome.CONFLICT
        assert not repo.confirmed
        assert not repo.waiting

    def test_name_required_when_user_has_none(self):
        service = _service(
            FakeRepo(session=_session_ctx()), users=FakeUsers(_user(name=""))
        )

        with pytest.raises(AnonymousEnrollmentError) as excinfo:
            service.enroll(_request(), "")

        assert _error_code(excinfo) == AnonymousEnrollmentErrorCode.NAME_REQUIRED


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
        assert repo.deleted == [(_SESSION_ID, _USER_PK)]
        assert promotion.filled == [_SESSION_ID]

    def test_cancel_waiting_seat_does_not_promote(self):
        repo = FakeRepo(
            session=_session_ctx(),
            participation_status=SessionParticipationStatus.WAITING,
        )
        promotion = FakePromotion()
        service = _service(repo=repo, promotion=promotion)

        result = service.cancel(_request(), "Ala")

        assert result.cancelled is True
        assert not promotion.filled

    def test_cancel_without_enrollment(self):
        repo = FakeRepo(session=_session_ctx(), participation_status=None)
        promotion = FakePromotion()
        service = _service(repo=repo, promotion=promotion)

        result = service.cancel(_request(), "Ala")

        assert result.cancelled is False
        assert not promotion.filled

    def test_cancel_allowed_when_enrollment_closed(self):
        repo = FakeRepo(
            session=_session_ctx(allows_anonymous_enrollment=False),
            participation_status=SessionParticipationStatus.CONFIRMED,
        )
        service = _service(repo=repo)

        result = service.cancel(_request(), "Ala")

        assert result.cancelled is True


class TestLoadByCode:
    def test_returns_load(self):
        load = AnonymousLoadDTO(event_id=_EVENT_ID, event_slug="conv", site_id=_SITE_ID)
        service = _service(repo=FakeRepo(load=load))

        assert service.load_by_code(code=_CODE) == load

    def test_unknown_code(self):
        service = _service(repo=FakeRepo(), users=FakeUsers(None))

        with pytest.raises(AnonymousEnrollmentError) as excinfo:
            service.load_by_code(code="nope")

        assert _error_code(excinfo) == AnonymousEnrollmentErrorCode.USER_NOT_FOUND

    def test_no_enrollments(self):
        service = _service(repo=FakeRepo(load=None))

        with pytest.raises(AnonymousEnrollmentError) as excinfo:
            service.load_by_code(code=_CODE)

        assert _error_code(excinfo) == AnonymousEnrollmentErrorCode.NO_ENROLLMENTS
