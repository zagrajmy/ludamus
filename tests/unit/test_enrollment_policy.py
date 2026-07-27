from dataclasses import dataclass

from ludamus.pacts.enrollment import EnrollmentPolicy


@dataclass
class _Window:
    percentage_slots: int = 100
    max_waitlist_sessions: int = 0
    restrict_to_configured_users: bool = False
    allow_anonymous_enrollment: bool = False
    banner_text: str = ""


_OPEN_PERCENT = 20
_RESTRICTED_PERCENT = 100
_SESSION_LIMIT = 100
_WIDE_WAITLIST = 5
_NARROW_WAITLIST = 1
_UNLIMITED = 1_000


def _policy(*windows: _Window, is_configured_user: bool = False) -> EnrollmentPolicy:
    return EnrollmentPolicy.for_actor(windows, is_configured_user=is_configured_user)


class TestWindowSelection:
    def test_cannot_enroll_without_any_window(self) -> None:
        assert _policy().can_enroll is False

    def test_open_window_admits_an_unconfigured_actor(self) -> None:
        assert _policy(_Window()).can_enroll is True

    def test_restricted_window_is_not_usable_by_an_unconfigured_actor(self) -> None:
        assert _policy(_Window(restrict_to_configured_users=True)).can_enroll is False

    def test_restricted_window_is_usable_by_a_configured_actor(self) -> None:
        policy = _policy(
            _Window(restrict_to_configured_users=True), is_configured_user=True
        )

        assert policy.can_enroll is True

    def test_open_window_still_admits_when_another_window_restricts(self) -> None:
        policy = _policy(_Window(restrict_to_configured_users=True), _Window())

        assert policy.can_enroll is True


class TestCapacityStaysInsideUsableWindows:
    def test_unconfigured_actor_cannot_draw_on_a_restricted_pool(self) -> None:
        policy = _policy(
            _Window(
                percentage_slots=_RESTRICTED_PERCENT, restrict_to_configured_users=True
            ),
            _Window(percentage_slots=_OPEN_PERCENT),
        )

        assert policy.percentage_slots == _OPEN_PERCENT
        assert (
            policy.available_slots(participants_limit=_SESSION_LIMIT, enrolled_count=0)
            == _OPEN_PERCENT
        )

    def test_configured_actor_gets_the_wider_pool(self) -> None:
        policy = _policy(
            _Window(
                percentage_slots=_RESTRICTED_PERCENT, restrict_to_configured_users=True
            ),
            _Window(percentage_slots=_OPEN_PERCENT),
            is_configured_user=True,
        )

        assert (
            policy.available_slots(participants_limit=_SESSION_LIMIT, enrolled_count=0)
            == _RESTRICTED_PERCENT
        )

    def test_available_slots_subtracts_the_enrolled(self) -> None:
        policy = _policy(_Window(percentage_slots=50))

        assert (
            policy.available_slots(participants_limit=_SESSION_LIMIT, enrolled_count=30)
            == _OPEN_PERCENT
        )

    def test_available_slots_never_goes_negative(self) -> None:
        policy = _policy(_Window(percentage_slots=10))

        assert policy.available_slots(participants_limit=100, enrolled_count=80) == 0

    def test_unlimited_session_stays_unlimited(self) -> None:
        policy = _policy(_Window(percentage_slots=50))

        assert (
            policy.available_slots(participants_limit=0, enrolled_count=99) > _UNLIMITED
        )


class TestAggregates:
    def test_waiting_list_takes_the_highest_usable_window(self) -> None:
        policy = _policy(
            _Window(max_waitlist_sessions=2),
            _Window(max_waitlist_sessions=_WIDE_WAITLIST),
        )

        assert policy.max_waitlist_sessions == _WIDE_WAITLIST

    def test_waiting_list_ignores_a_window_the_actor_cannot_use(self) -> None:
        policy = _policy(
            _Window(max_waitlist_sessions=9, restrict_to_configured_users=True),
            _Window(max_waitlist_sessions=_NARROW_WAITLIST),
        )

        assert policy.max_waitlist_sessions == _NARROW_WAITLIST

    def test_anonymous_enrollment_needs_only_one_window_allowing_it(self) -> None:
        policy = _policy(_Window(), _Window(allow_anonymous_enrollment=True))

        assert policy.allows_anonymous_enrollment is True

    def test_banner_comes_from_the_first_window_that_has_one(self) -> None:
        policy = _policy(_Window(), _Window(banner_text="Zapisy trwają"))

        assert policy.banner_text == "Zapisy trwają"
