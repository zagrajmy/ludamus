from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from ludamus.mills.enrollment import (
    EnrollmentService,
    can_enroll_users,
    get_used_slots,
    get_vc_available_slots,
)
from ludamus.pacts.crowd import UserDTO, UserType
from ludamus.pacts.enrollment import EnrollmentRepos
from ludamus.pacts.legacy import (
    EnrollmentConfigDTO,
    EventDTO,
    UserEnrollmentConfigDTO,
    VirtualEnrollmentConfig,
)

_NOW = datetime(2026, 6, 4, 12, 0, tzinfo=UTC)
_EVENT_ID = 11
_CHECK_INTERVAL = 60
_ALLOWED_SLOTS = 3
_SESSION_ID = 42
_PARTY_ID = 9
_GUEST_COUNT = 2


def _user(pk, slug="viewer", email="viewer@example.com", name="Viewer"):
    return UserDTO(
        avatar_url="",
        date_joined=_NOW,
        discord_username="",
        email=email,
        full_name=name,
        is_active=True,
        is_authenticated=True,
        is_staff=False,
        is_superuser=False,
        name=name,
        pk=pk,
        slug=slug,
        use_gravatar=False,
        user_type=UserType.ACTIVE,
        username=slug,
    )


def _event(pk=_EVENT_ID):
    return EventDTO(
        description="",
        end_time=_NOW + timedelta(days=2),
        name="Konwencik",
        pk=pk,
        proposal_end_time=None,
        proposal_start_time=None,
        publication_time=None,
        slug="konwencik",
        sphere_id=1,
        start_time=_NOW + timedelta(days=1),
    )


def _enrollment_config(pk=5):
    return EnrollmentConfigDTO(
        allow_anonymous_enrollment=False,
        banner_text="",
        end_time=_NOW + timedelta(days=1),
        event_id=_EVENT_ID,
        limit_to_end_time=False,
        max_waitlist_sessions=3,
        percentage_slots=100,
        pk=pk,
        restrict_to_configured_users=True,
        start_time=_NOW - timedelta(days=1),
    )


def _user_config(allowed_slots):
    return UserEnrollmentConfigDTO(
        allowed_slots=allowed_slots,
        enrollment_config_id=5,
        fetched_from_api=False,
        last_check=_NOW,
        pk=17,
        user_email="viewer@example.com",
    )


@contextmanager
def _atomic():
    yield


class FakeTransaction:
    def __init__(self):
        self.atomic_entered = 0

    def atomic(self):
        self.atomic_entered += 1
        return _atomic()


class FakeParticipations:
    def __init__(self, occupying=frozenset()):
        self._occupying = set(occupying)
        self.queries: list[dict] = []
        self.created: list[object] = []

    def occupying_user_ids(self, *, user_ids, event_id):
        self.queries.append({"user_ids": list(user_ids), "event_id": event_id})
        return self._occupying & set(user_ids)

    def create_confirmed(self, seat):
        self.created.append(seat)


class FakeUsers:
    def __init__(self, users=()):
        self._by_slug = {user.slug: user for user in users}
        self.created: list[dict] = []

    def create(self, user_data):
        self.created.append(dict(user_data))
        self._by_slug[user_data["slug"]] = _user(
            pk=1000 + len(self.created),
            slug=user_data["slug"],
            email="",
            name=user_data.get("name", ""),
        )

    def read(self, slug):
        return self._by_slug[slug]

    def read_by_ids(self, pks):
        return sorted(
            (user for user in self._by_slug.values() if user.pk in pks),
            key=lambda user: user.pk,
        )


class FakeEnrollmentConfigs:
    def __init__(self, configs=(), user_config=None):
        self._configs = list(configs)
        self._user_config = user_config

    def read_list(self, _event_id, **_time_window):
        return list(self._configs)

    def read_user_config(self, _config, _user_email):
        return self._user_config

    def read_domain_config(self, _config, _domain):
        return None


class FakeTicketAPI:
    def __init__(self):
        self.calls: list[str] = []

    def fetch_membership_count(self, user_email):
        self.calls.append(user_email)
        return 0


def _service(
    *, users=None, anonymous_users=None, enrollment_configs=None, participations=None
):
    return EnrollmentService(
        transaction=FakeTransaction(),
        repos=EnrollmentRepos(
            users=users if users is not None else FakeUsers(),
            anonymous_users=(
                anonymous_users if anonymous_users is not None else FakeUsers()
            ),
            enrollment_configs=(
                enrollment_configs
                if enrollment_configs is not None
                else FakeEnrollmentConfigs()
            ),
            participations=(
                participations if participations is not None else FakeParticipations()
            ),
            ticket_api=FakeTicketAPI(),
        ),
        membership_check_interval=_CHECK_INTERVAL,
    )


class TestSlotMath:
    def test_get_used_slots_counts_distinct_occupying_users(self):
        occupying = {1, 2}
        participations = FakeParticipations(occupying=occupying)

        used = get_used_slots(
            users=[_user(1), _user(2), _user(3)],
            event=_event(),
            participations=participations,
        )

        assert used == len(occupying)
        assert participations.queries == [
            {"user_ids": [1, 2, 3], "event_id": _EVENT_ID}
        ]

    def test_can_enroll_users_allows_within_limit(self):
        allowed = can_enroll_users(
            users=[_user(1), _user(2)],
            event=_event(),
            virtual_config=VirtualEnrollmentConfig(allowed_slots=2),
            users_to_enroll=[_user(2)],
            participations=FakeParticipations(occupying={1}),
        )

        assert allowed is True

    def test_can_enroll_users_rejects_over_limit(self):
        allowed = can_enroll_users(
            users=[_user(1), _user(2)],
            event=_event(),
            virtual_config=VirtualEnrollmentConfig(allowed_slots=1),
            users_to_enroll=[_user(2)],
            participations=FakeParticipations(occupying={1}),
        )

        assert allowed is False

    def test_can_enroll_users_does_not_double_count_enrolled_user(self):
        allowed = can_enroll_users(
            users=[_user(1)],
            event=_event(),
            virtual_config=VirtualEnrollmentConfig(allowed_slots=1),
            users_to_enroll=[_user(1)],
            participations=FakeParticipations(occupying={1}),
        )

        assert allowed is True

    def test_get_vc_available_slots_subtracts_used(self):
        available = get_vc_available_slots(
            users=[_user(1), _user(2)],
            event=_event(),
            virtual_config=VirtualEnrollmentConfig(allowed_slots=_ALLOWED_SLOTS),
            participations=FakeParticipations(occupying={1}),
        )

        assert available == _ALLOWED_SLOTS - 1

    def test_get_vc_available_slots_clamps_at_zero(self):
        available = get_vc_available_slots(
            users=[_user(1), _user(2)],
            event=_event(),
            virtual_config=VirtualEnrollmentConfig(allowed_slots=1),
            participations=FakeParticipations(occupying={1, 2}),
        )

        assert available == 0


class TestEnrollmentService:
    def test_read_viewer_returns_user_by_slug(self):
        viewer = _user(1)
        service = _service(users=FakeUsers([viewer]))

        assert service.read_viewer("viewer") == viewer

    def test_read_users_returns_users_by_ids(self):
        first, second = _user(1, slug="a"), _user(2, slug="b")
        service = _service(users=FakeUsers([first, second]))

        assert service.read_users([2]) == [second]

    def test_virtual_config_combines_stored_user_config(self):
        service = _service(
            enrollment_configs=FakeEnrollmentConfigs(
                configs=[_enrollment_config()], user_config=_user_config(4)
            )
        )

        config = service.virtual_config(event=_event(), user_email="viewer@example.com")

        assert config == VirtualEnrollmentConfig(
            allowed_slots=4, has_domain_config=False, has_user_config=True
        )

    def test_has_slot_access_false_without_email(self):
        ticket_api = FakeTicketAPI()
        service = EnrollmentService(
            transaction=FakeTransaction(),
            repos=EnrollmentRepos(
                users=FakeUsers(),
                anonymous_users=FakeUsers(),
                enrollment_configs=FakeEnrollmentConfigs(
                    configs=[_enrollment_config()], user_config=_user_config(4)
                ),
                participations=FakeParticipations(),
                ticket_api=ticket_api,
            ),
            membership_check_interval=_CHECK_INTERVAL,
        )

        assert service.has_slot_access(event=_event(), user_email="") is False
        assert not ticket_api.calls

    def test_has_slot_access_true_with_allowed_slots(self):
        service = _service(
            enrollment_configs=FakeEnrollmentConfigs(
                configs=[_enrollment_config()], user_config=_user_config(2)
            )
        )

        access = service.has_slot_access(
            event=_event(), user_email="viewer@example.com"
        )

        assert access is True

    def test_has_slot_access_false_without_config(self):
        service = _service(enrollment_configs=FakeEnrollmentConfigs())

        access = service.has_slot_access(
            event=_event(), user_email="viewer@example.com"
        )

        assert access is False

    def test_get_used_slots_delegates_to_injected_repo(self):
        service = _service(participations=FakeParticipations(occupying={1}))

        used = service.get_used_slots(users=[_user(1), _user(2)], event=_event())

        assert used == 1

    def test_can_enroll_users_uses_injected_repo(self):
        service = _service(participations=FakeParticipations(occupying={1}))

        allowed = service.can_enroll_users(
            users=[_user(1), _user(2)],
            event=_event(),
            virtual_config=VirtualEnrollmentConfig(allowed_slots=1),
            users_to_enroll=[_user(2)],
        )

        assert allowed is False

    def test_get_vc_available_slots_uses_injected_repo(self):
        service = _service(participations=FakeParticipations(occupying={1}))

        available = service.get_vc_available_slots(
            users=[_user(1)],
            event=_event(),
            virtual_config=VirtualEnrollmentConfig(allowed_slots=_ALLOWED_SLOTS),
        )

        assert available == _ALLOWED_SLOTS - 1

    def test_create_guests_creates_users_and_confirmed_seats_atomically(self):
        anonymous_users = FakeUsers()
        participations = FakeParticipations()
        transaction = FakeTransaction()
        service = EnrollmentService(
            transaction=transaction,
            repos=EnrollmentRepos(
                users=FakeUsers(),
                anonymous_users=anonymous_users,
                enrollment_configs=FakeEnrollmentConfigs(),
                participations=participations,
                ticket_api=FakeTicketAPI(),
            ),
            membership_check_interval=_CHECK_INTERVAL,
        )

        service.create_guests(
            session_id=_SESSION_ID,
            count=_GUEST_COUNT,
            party_id=_PARTY_ID,
            enrolled_by_id=1,
            viewer_name="Wanda Wiewiórka",
        )

        assert transaction.atomic_entered == 1
        assert len(anonymous_users.created) == _GUEST_COUNT
        assert all(
            data["slug"].startswith("guest-") for data in anonymous_users.created
        )
        assert all(
            data["name"] == "Wanda Wiewiórka +1" for data in anonymous_users.created
        )
        assert len(participations.created) == _GUEST_COUNT
        assert all(seat.session_id == _SESSION_ID for seat in participations.created)
        assert all(seat.party_id == _PARTY_ID for seat in participations.created)
        assert all(seat.enrolled_by_id == 1 for seat in participations.created)

    def test_create_guests_with_zero_count_creates_nothing(self):
        anonymous_users = FakeUsers()
        participations = FakeParticipations()
        service = _service(
            anonymous_users=anonymous_users, participations=participations
        )

        service.create_guests(
            session_id=_SESSION_ID,
            count=0,
            party_id=None,
            enrolled_by_id=1,
            viewer_name="Wanda",
        )

        assert not anonymous_users.created
        assert not participations.created
