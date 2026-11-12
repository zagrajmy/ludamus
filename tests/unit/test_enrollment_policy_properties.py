"""Properties of enrollment windows, checked against the real policy.

The windows decide how many seats an actor sees and when they may enroll.
Holding a pass must never make either worse, and the seat arithmetic must stay
inside the room. `HYPOTHESIS_PROFILE=crosshair` hands the integer arithmetic to
CrossHair's solver, which hunts the rounding edges directly.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from hypothesis import given
from hypothesis import strategies as st

from ludamus.mills.enrollment_windows import EnrollmentPolicy, viewer_access

_EPOCH = datetime(2026, 6, 1, tzinfo=UTC)


@dataclass(frozen=True)
class Window:
    pk: int
    start_time: datetime
    end_time: datetime
    percentage_slots: int
    restrict_to_configured_users: bool
    allow_anonymous_enrollment: bool = False
    max_waitlist_sessions: int = 10


@st.composite
def windows(draw: st.DrawFn) -> list[Window]:
    count = draw(st.integers(min_value=0, max_value=4))
    result = []
    for pk in range(1, count + 1):
        start = draw(st.integers(min_value=0, max_value=48))
        length = draw(st.integers(min_value=1, max_value=48))
        result.append(
            Window(
                pk=pk,
                start_time=_EPOCH + timedelta(hours=start),
                end_time=_EPOCH + timedelta(hours=start + length),
                percentage_slots=draw(st.integers(min_value=1, max_value=100)),
                restrict_to_configured_users=draw(st.booleans()),
            )
        )
    return result


limits = st.integers(min_value=0, max_value=500)


@given(windows(), limits)
def test_a_pass_never_lowers_the_seats_on_offer(listed, limit):
    holder = EnrollmentPolicy.for_actor(listed, is_configured_user=True)
    guest = EnrollmentPolicy.for_guest(listed)

    assert holder.effective_participants_limit(
        participants_limit=limit
    ) >= guest.effective_participants_limit(participants_limit=limit)


@given(windows(), limits)
def test_never_offers_more_seats_than_the_room_has(listed, limit):
    policy = EnrollmentPolicy.for_actor(listed, is_configured_user=True)

    assert 0 <= policy.effective_participants_limit(participants_limit=limit) <= limit


@given(windows(), st.integers(min_value=1, max_value=500))
def test_an_open_window_always_offers_a_seat(listed, limit):
    policy = EnrollmentPolicy.for_guest(listed)

    if policy.can_enroll:
        assert policy.effective_participants_limit(participants_limit=limit) >= 1


@given(windows(), limits, st.integers(min_value=0, max_value=600))
def test_full_exactly_when_no_seat_is_left(listed, limit, enrolled):
    policy = EnrollmentPolicy.for_actor(listed, is_configured_user=True)

    if policy.can_enroll:
        assert policy.is_full(participants_limit=limit, enrolled_count=enrolled) == (
            policy.available_slots(participants_limit=limit, enrolled_count=enrolled)
            == 0
        )


@given(
    windows(),
    st.sets(st.integers(min_value=1, max_value=4)),
    st.integers(min_value=0, max_value=96),
)
def test_a_pass_never_hides_a_window_or_delays_the_next(listed, passes, hour):
    now = _EPOCH + timedelta(hours=hour)

    with_passes = viewer_access(
        windows=listed, configured_window_ids=frozenset(passes), now=now
    )
    without = viewer_access(windows=listed, configured_window_ids=frozenset(), now=now)

    assert with_passes.open_window_ids >= without.open_window_ids
    if without.opens_at is not None:
        assert with_passes.opens_at is not None
        assert with_passes.opens_at <= without.opens_at
