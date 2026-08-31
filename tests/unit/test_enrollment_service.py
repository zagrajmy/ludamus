from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from ludamus.mills.enrollment import (
    EnrollmentService,
    can_enroll_users,
    get_used_slots,
    get_vc_available_slots,
)
from ludamus.mills.enrollment_windows import viewer_access
from ludamus.pacts.crowd import UserDTO, UserType
from ludamus.pacts.enrollment import EnrollmentAccessDTO, EnrollmentRepos
from ludamus.pacts.legacy import (
    DomainEnrollmentConfigDTO,
    EnrollmentConfigDTO,
    EventDTO,
    MembershipAPIError,
    UserEnrollmentConfigDTO,
    VirtualEnrollmentConfig,
)

_NOW = datetime(2026, 6, 4, 12, 0, tzinfo=UTC)
_EVENT_ID = 11
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


def _enrollment_config(
    pk=5, *, start_time=None, end_time=None, restrict_to_configured_users=True
):
    # Open now unless the caller says otherwise: virtual_config asks the repo
    # for the windows open at the real clock, not at _NOW.
    now = datetime.now(tz=UTC)
    start_time = now - timedelta(days=1) if start_time is None else start_time
    end_time = now + timedelta(days=1) if end_time is None else end_time
    return EnrollmentConfigDTO(
        allow_anonymous_enrollment=False,
        banner_text="",
        end_time=end_time,
        event_id=_EVENT_ID,
        limit_to_end_time=False,
        max_waitlist_sessions=3,
        percentage_slots=100,
        pk=pk,
        restrict_to_configured_users=restrict_to_configured_users,
        start_time=start_time,
    )


def _user_config(allowed_slots, *, last_check=_NOW):
    return UserEnrollmentConfigDTO(
        allowed_slots=allowed_slots,
        enrollment_config_id=5,
        fetched_from_api=False,
        last_check=last_check,
        pk=17,
        user_email="viewer@example.com",
    )


def _domain_config(allowed_slots_per_user):
    return DomainEnrollmentConfigDTO(
        pk=23,
        enrollment_config_id=5,
        domain="example.com",
        allowed_slots_per_user=allowed_slots_per_user,
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
    def __init__(self, configs=(), user_config=None, domain_config=None):
        self._configs = list(configs)
        self._user_config = user_config
        self._domain_config = domain_config
        self.created: list[dict] = []
        self.updated: list[UserEnrollmentConfigDTO] = []

    def read_list(self, _event_id, max_start_time, min_end_time):
        # The real repo bounds the period; a fake that ignores it lets a test
        # pass on windows the service would never have been handed.
        return [
            config
            for config in self._configs
            if config.start_time <= max_start_time and config.end_time >= min_end_time
        ]

    def create_user_config(self, user_enrollment_config):
        self.created.append(dict(user_enrollment_config))
        self._user_config = UserEnrollmentConfigDTO(
            pk=17 + len(self.created), **user_enrollment_config
        )
        return self._user_config

    def update_user_config(self, user_enrollment_config):
        self.updated.append(user_enrollment_config)

    def read_user_config(self, _config, _user_email):
        return self._user_config

    def read_domain_config(self, config, domain):
        if self._domain_config is None:
            return None
        matches = (
            self._domain_config.enrollment_config_id == config.pk
            and self._domain_config.domain == domain
        )
        return self._domain_config if matches else None


class FakeWindows:
    def __init__(self, windows=()):
        self._windows = list(windows)

    def list_for_event(self, _event_id):
        return list(self._windows)


class FakeTicketAPI:
    def __init__(self, membership_count=0):
        self.calls: list[str] = []
        self._membership_count = membership_count

    def fetch_membership_count(self, user_email):
        self.calls.append(user_email)
        return self._membership_count


class NoTicketAPI:
    # What the resolver hands back for an event with no usable ticketing
    # integration: one way to say "no answer available".
    def fetch_membership_count(self, user_email):
        raise MembershipAPIError


class FakeTicketApiResolver:
    def __init__(self, ticket_api=None):
        self.ticket_api = ticket_api or NoTicketAPI()
        self.seen: list[tuple[int, int]] = []

    def resolve(self, *, event_id, sphere_id):
        self.seen.append((event_id, sphere_id))
        return self.ticket_api


def _service(
    *,
    users=None,
    anonymous_users=None,
    enrollment_configs=None,
    participations=None,
    ticket_api_resolver=None,
    windows=None,
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
            ticket_api_resolver=(
                ticket_api_resolver
                if ticket_api_resolver is not None
                else FakeTicketApiResolver(FakeTicketAPI())
            ),
            windows=windows if windows is not None else FakeWindows(),
        ),
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
            virtual_config=VirtualEnrollmentConfig(user_slots=2),
            users_to_enroll=[_user(2)],
            participations=FakeParticipations(occupying={1}),
        )

        assert allowed is True

    def test_can_enroll_users_rejects_over_limit(self):
        allowed = can_enroll_users(
            users=[_user(1), _user(2)],
            event=_event(),
            virtual_config=VirtualEnrollmentConfig(user_slots=1),
            users_to_enroll=[_user(2)],
            participations=FakeParticipations(occupying={1}),
        )

        assert allowed is False

    def test_can_enroll_users_does_not_double_count_enrolled_user(self):
        allowed = can_enroll_users(
            users=[_user(1)],
            event=_event(),
            virtual_config=VirtualEnrollmentConfig(user_slots=1),
            users_to_enroll=[_user(1)],
            participations=FakeParticipations(occupying={1}),
        )

        assert allowed is True

    def test_get_vc_available_slots_subtracts_used(self):
        available = get_vc_available_slots(
            users=[_user(1), _user(2)],
            event=_event(),
            virtual_config=VirtualEnrollmentConfig(user_slots=_ALLOWED_SLOTS),
            participations=FakeParticipations(occupying={1}),
        )

        assert available == _ALLOWED_SLOTS - 1

    def test_get_vc_available_slots_clamps_at_zero(self):
        available = get_vc_available_slots(
            users=[_user(1), _user(2)],
            event=_event(),
            virtual_config=VirtualEnrollmentConfig(user_slots=1),
            participations=FakeParticipations(occupying={1, 2}),
        )

        assert available == 0


def _window_open_at_now(pk=5, *, restrict_to_configured_users=True):
    return _enrollment_config(
        pk,
        start_time=_NOW - timedelta(days=1),
        end_time=_NOW + timedelta(days=1),
        restrict_to_configured_users=restrict_to_configured_users,
    )


class TestEnrollmentAccess:
    def test_a_restricted_window_is_shut_for_a_viewer_without_passes(self):
        access = viewer_access(
            windows=[_window_open_at_now()], configured_window_ids=frozenset(), now=_NOW
        )

        assert access == EnrollmentAccessDTO(open_window_ids=frozenset(), opens_at=None)

    def test_a_restricted_window_is_open_for_a_pass_holder(self):
        access = viewer_access(
            windows=[_window_open_at_now()],
            configured_window_ids=frozenset({5}),
            now=_NOW,
        )

        assert access == EnrollmentAccessDTO(
            open_window_ids=frozenset({5}), opens_at=None
        )

    def test_the_earliest_window_the_viewer_may_use_is_the_one_named(self):
        general = _NOW + timedelta(days=2)
        access = viewer_access(
            windows=[
                _enrollment_config(
                    pk=6,
                    start_time=_NOW + timedelta(days=1),
                    end_time=_NOW + timedelta(days=4),
                ),
                _enrollment_config(
                    pk=7,
                    start_time=general,
                    end_time=_NOW + timedelta(days=5),
                    restrict_to_configured_users=False,
                ),
            ],
            configured_window_ids=frozenset(),
            now=_NOW,
        )

        assert access == EnrollmentAccessDTO(
            open_window_ids=frozenset(), opens_at=general
        )

    def test_a_window_that_has_ended_is_not_something_to_wait_for(self):
        access = viewer_access(
            windows=[
                _enrollment_config(
                    start_time=_NOW - timedelta(days=3),
                    end_time=_NOW - timedelta(days=2),
                    restrict_to_configured_users=False,
                )
            ],
            configured_window_ids=frozenset(),
            now=_NOW,
        )

        assert access == EnrollmentAccessDTO(open_window_ids=frozenset(), opens_at=None)

    def test_an_open_window_is_named_by_id_so_a_session_can_be_asked_about(self):
        access = viewer_access(
            windows=[
                _window_open_at_now(),
                _window_open_at_now(pk=6, restrict_to_configured_users=False),
            ],
            configured_window_ids=frozenset(),
            now=_NOW,
        )

        assert access == EnrollmentAccessDTO(
            open_window_ids=frozenset({6}), opens_at=None
        )


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

        assert config == VirtualEnrollmentConfig(user_slots=4)

    def test_virtual_config_is_none_for_a_stored_row_granting_no_slots(self):
        # A stale zero-slot row would normally trigger a refresh; with no
        # integration the stored row stands, and granting nothing is not
        # access, so the page says "no enrollment passes" instead of "up to 0".
        service = _service(
            enrollment_configs=FakeEnrollmentConfigs(
                configs=[_enrollment_config()], user_config=_user_config(0)
            ),
            ticket_api_resolver=FakeTicketApiResolver(),
        )

        config = service.virtual_config(event=_event(), user_email="viewer@example.com")

        assert config is None

    def test_virtual_config_reports_domain_only_access_for_a_zero_slot_user_row(self):
        # A user row exists but grants nothing, so every slot comes from the
        # domain. The page names the domain rather than the flag that used to
        # stand in for it.
        service = _service(
            enrollment_configs=FakeEnrollmentConfigs(
                configs=[_enrollment_config()],
                user_config=_user_config(0),
                domain_config=_domain_config(2),
            ),
            ticket_api_resolver=FakeTicketApiResolver(),
        )

        config = service.virtual_config(event=_event(), user_email="viewer@example.com")

        assert config == VirtualEnrollmentConfig(domain_slots=2, domain="example.com")

    def test_virtual_config_is_none_for_a_domain_row_granting_no_slots(self):
        # A domain row that grants nothing is not access either: naming the
        # domain would promise access the slot check then refuses.
        service = _service(
            enrollment_configs=FakeEnrollmentConfigs(
                configs=[_enrollment_config()], domain_config=_domain_config(0)
            ),
            ticket_api_resolver=FakeTicketApiResolver(),
        )

        config = service.virtual_config(event=_event(), user_email="viewer@example.com")

        assert config is None

    def test_virtual_config_ignores_a_domain_row_for_another_domain(self):
        service = _service(
            enrollment_configs=FakeEnrollmentConfigs(
                configs=[_enrollment_config()], domain_config=_domain_config(2)
            ),
            ticket_api_resolver=FakeTicketApiResolver(),
        )

        config = service.virtual_config(event=_event(), user_email="viewer@other.org")

        assert config is None

    def test_virtual_config_is_none_without_integration_and_without_stored_config(self):
        service = _service(
            enrollment_configs=FakeEnrollmentConfigs(configs=[_enrollment_config()]),
            ticket_api_resolver=FakeTicketApiResolver(),
        )

        config = service.virtual_config(event=_event(), user_email="viewer@example.com")

        assert config is None

    def test_virtual_config_does_not_resolve_ticketing_without_an_open_window(self):
        resolver = FakeTicketApiResolver(FakeTicketAPI())
        service = _service(
            enrollment_configs=FakeEnrollmentConfigs(), ticket_api_resolver=resolver
        )

        service.virtual_config(event=_event(), user_email="viewer@example.com")

        assert not resolver.seen

    def test_virtual_config_resolves_ticketing_once_across_windows(self):
        resolver = FakeTicketApiResolver(FakeTicketAPI())
        service = _service(
            enrollment_configs=FakeEnrollmentConfigs(
                configs=[_enrollment_config(), _enrollment_config(pk=6)],
                user_config=_user_config(4),
            ),
            ticket_api_resolver=resolver,
        )

        service.virtual_config(event=_event(), user_email="viewer@example.com")

        assert resolver.seen == [(_EVENT_ID, 1)]

    def test_virtual_config_sums_slots_across_open_windows(self):
        slots = 4
        service = _service(
            enrollment_configs=FakeEnrollmentConfigs(
                configs=[_enrollment_config(), _enrollment_config(pk=6)],
                user_config=_user_config(slots),
            )
        )

        config = service.virtual_config(event=_event(), user_email="viewer@example.com")

        assert config == VirtualEnrollmentConfig(user_slots=slots + slots)

    def test_virtual_config_combines_user_slots_with_domain_slots(self):
        service = _service(
            enrollment_configs=FakeEnrollmentConfigs(
                configs=[_enrollment_config()],
                user_config=_user_config(4),
                domain_config=_domain_config(2),
            )
        )

        config = service.virtual_config(event=_event(), user_email="viewer@example.com")

        assert config == VirtualEnrollmentConfig(
            user_slots=4, domain_slots=2, domain="example.com"
        )

    def test_virtual_config_stores_the_membership_the_api_reports(self):
        configs = FakeEnrollmentConfigs(configs=[_enrollment_config()])
        slots = 7
        service = _service(
            enrollment_configs=configs,
            ticket_api_resolver=FakeTicketApiResolver(FakeTicketAPI(slots)),
        )

        config = service.virtual_config(event=_event(), user_email="viewer@example.com")

        assert config == VirtualEnrollmentConfig(user_slots=slots)
        assert [row["allowed_slots"] for row in configs.created] == [slots]
        assert [row["fetched_from_api"] for row in configs.created] == [True]

    def test_virtual_config_is_none_when_the_api_reports_no_membership(self):
        configs = FakeEnrollmentConfigs(configs=[_enrollment_config()])
        service = _service(
            enrollment_configs=configs,
            ticket_api_resolver=FakeTicketApiResolver(FakeTicketAPI(0)),
        )

        config = service.virtual_config(event=_event(), user_email="viewer@example.com")

        assert config is None
        # The row is stored all the same, so the next read is throttled
        # instead of asking the API again.
        assert [row["allowed_slots"] for row in configs.created] == [0]

    def test_virtual_config_refetches_a_stale_row_granting_no_slots(self):
        configs = FakeEnrollmentConfigs(
            configs=[_enrollment_config()],
            user_config=_user_config(0, last_check=_NOW - timedelta(days=10)),
        )
        slots = 7
        ticket_api = FakeTicketAPI(slots)
        service = _service(
            enrollment_configs=configs,
            ticket_api_resolver=FakeTicketApiResolver(ticket_api),
        )

        config = service.virtual_config(event=_event(), user_email="viewer@example.com")

        assert config == VirtualEnrollmentConfig(user_slots=slots)
        assert ticket_api.calls == ["viewer@example.com"]
        assert [row.allowed_slots for row in configs.updated] == [slots]

    def test_virtual_config_keeps_a_refetched_row_that_still_grants_nothing(self):
        configs = FakeEnrollmentConfigs(
            configs=[_enrollment_config()],
            user_config=_user_config(0, last_check=_NOW - timedelta(days=10)),
        )
        service = _service(
            enrollment_configs=configs,
            ticket_api_resolver=FakeTicketApiResolver(FakeTicketAPI(0)),
        )

        config = service.virtual_config(event=_event(), user_email="viewer@example.com")

        assert config is None
        assert [row.allowed_slots for row in configs.updated] == [0]

    def test_virtual_config_survives_a_membership_api_failure_with_no_row(self):
        # The API is the only source of a first row, so a failure leaves the
        # viewer without access rather than with an invented allowance.
        configs = FakeEnrollmentConfigs(configs=[_enrollment_config()])
        service = _service(
            enrollment_configs=configs,
            ticket_api_resolver=FakeTicketApiResolver(NoTicketAPI()),
        )

        config = service.virtual_config(event=_event(), user_email="viewer@example.com")

        assert config is None
        assert not configs.created

    def test_virtual_config_writes_nothing_when_a_refetch_fails(self):
        # A failing API is not an answer: the stored row stands, unwritten, and
        # the next read tries again instead of trusting a blank.
        configs = FakeEnrollmentConfigs(
            configs=[_enrollment_config()],
            user_config=_user_config(0, last_check=_NOW - timedelta(days=10)),
        )
        service = _service(
            enrollment_configs=configs,
            ticket_api_resolver=FakeTicketApiResolver(NoTicketAPI()),
        )

        config = service.virtual_config(event=_event(), user_email="viewer@example.com")

        assert config is None
        assert not configs.updated

    def test_virtual_config_does_not_refetch_a_row_checked_recently(self):
        ticket_api = FakeTicketAPI(7)
        service = _service(
            enrollment_configs=FakeEnrollmentConfigs(
                configs=[_enrollment_config()],
                user_config=_user_config(0, last_check=datetime.now(tz=UTC)),
            ),
            ticket_api_resolver=FakeTicketApiResolver(ticket_api),
        )

        config = service.virtual_config(event=_event(), user_email="viewer@example.com")

        assert config is None
        assert not ticket_api.calls

    def test_access_names_the_open_window_a_pass_holder_may_use(self):
        now = datetime.now(tz=UTC)
        windows = [
            _enrollment_config(
                start_time=now - timedelta(hours=1), end_time=now + timedelta(days=1)
            )
        ]
        service = _service(
            users=FakeUsers([_user(1)]),
            enrollment_configs=FakeEnrollmentConfigs(
                configs=windows, user_config=_user_config(4)
            ),
            windows=FakeWindows(windows),
        )

        access = service.access(event=_event(), viewer_slug="viewer")

        assert access == EnrollmentAccessDTO(
            open_window_ids=frozenset({5}), opens_at=None
        )

    def test_access_names_the_early_window_a_pass_holder_is_waiting_for(self):
        # The reader holds passes and no window is open yet. Their own window
        # is the answer, not the one everybody else waits for.
        now = datetime.now(tz=UTC)
        early_start = now + timedelta(days=1)
        windows = [
            _enrollment_config(
                start_time=early_start, end_time=now + timedelta(days=5)
            ),
            _enrollment_config(
                pk=6,
                start_time=now + timedelta(days=3),
                end_time=now + timedelta(days=5),
                restrict_to_configured_users=False,
            ),
        ]
        service = _service(
            users=FakeUsers([_user(1)]),
            enrollment_configs=FakeEnrollmentConfigs(
                configs=windows, user_config=_user_config(4)
            ),
            windows=FakeWindows(windows),
        )

        access = service.access(event=_event(), viewer_slug="viewer")

        assert access == EnrollmentAccessDTO(
            open_window_ids=frozenset(), opens_at=early_start
        )

    def test_access_names_the_general_window_for_a_viewer_without_passes(self):
        now = datetime.now(tz=UTC)
        general_start = now + timedelta(days=2)
        windows = [
            _enrollment_config(
                start_time=now - timedelta(hours=1), end_time=now + timedelta(days=1)
            ),
            _enrollment_config(
                pk=6,
                start_time=general_start,
                end_time=now + timedelta(days=3),
                restrict_to_configured_users=False,
            ),
        ]
        service = _service(
            users=FakeUsers([_user(1)]),
            enrollment_configs=FakeEnrollmentConfigs(configs=windows),
            windows=FakeWindows(windows),
            ticket_api_resolver=FakeTicketApiResolver(),
        )

        access = service.access(event=_event(), viewer_slug="viewer")

        assert access == EnrollmentAccessDTO(
            open_window_ids=frozenset(), opens_at=general_start
        )

    def test_access_asks_no_membership_question_without_a_restricted_window(self):
        now = datetime.now(tz=UTC)
        windows = [
            _enrollment_config(
                start_time=now - timedelta(hours=1),
                end_time=now + timedelta(days=1),
                restrict_to_configured_users=False,
            )
        ]
        ticket_api = FakeTicketAPI(7)
        service = _service(
            users=FakeUsers([_user(1)]),
            enrollment_configs=FakeEnrollmentConfigs(configs=windows),
            windows=FakeWindows(windows),
            ticket_api_resolver=FakeTicketApiResolver(ticket_api),
        )

        access = service.access(event=_event(), viewer_slug="viewer")

        assert access == EnrollmentAccessDTO(
            open_window_ids=frozenset({5}), opens_at=None
        )
        # Nothing turns on pass ownership here, and asking costs an API call.
        assert not ticket_api.calls

    def test_access_asks_no_membership_question_for_a_visitor(self):
        now = datetime.now(tz=UTC)
        windows = [
            _enrollment_config(
                start_time=now - timedelta(hours=1), end_time=now + timedelta(days=1)
            )
        ]
        ticket_api = FakeTicketAPI(7)
        service = _service(
            enrollment_configs=FakeEnrollmentConfigs(configs=windows),
            windows=FakeWindows(windows),
            ticket_api_resolver=FakeTicketApiResolver(ticket_api),
        )

        access = service.access(event=_event(), viewer_slug=None)

        assert access == EnrollmentAccessDTO(open_window_ids=frozenset(), opens_at=None)
        assert not ticket_api.calls

    def test_has_slot_access_false_without_email(self):
        ticket_api = FakeTicketAPI()
        service = _service(
            enrollment_configs=FakeEnrollmentConfigs(
                configs=[_enrollment_config()], user_config=_user_config(4)
            ),
            ticket_api_resolver=FakeTicketApiResolver(ticket_api),
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
            virtual_config=VirtualEnrollmentConfig(user_slots=1),
            users_to_enroll=[_user(2)],
        )

        assert allowed is False

    def test_get_vc_available_slots_uses_injected_repo(self):
        service = _service(participations=FakeParticipations(occupying={1}))

        available = service.get_vc_available_slots(
            users=[_user(1)],
            event=_event(),
            virtual_config=VirtualEnrollmentConfig(user_slots=_ALLOWED_SLOTS),
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
                ticket_api_resolver=FakeTicketApiResolver(FakeTicketAPI()),
                windows=FakeWindows(),
            ),
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
