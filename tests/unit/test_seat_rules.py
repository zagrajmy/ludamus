"""The seat and window rules every layer reads off `pacts.enrollment`.

Ways they could go wrong, each pinned below: a window counted open on the
moment it closes, or shut on the moment it opens; promotion losing the
allowance once every window has ended; a closed window zeroing a session's
cap (so nobody on the waiting list moves up); a share rounding a seat away;
a session that takes no enrollment reading as full.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ludamus.pacts.enrollment import (
    SessionSeatsDTO,
    allowance_windows,
    email_domain,
    open_windows,
    window_is_open,
)

_NOW = datetime(2026, 6, 1, 12, tzinfo=UTC)
_HOUR = timedelta(hours=1)
_LIMIT = 10


@dataclass(frozen=True)
class _Window:
    pk: int
    start_time: datetime
    end_time: datetime


class TestWindowIsOpen:
    def test_open_from_the_moment_it_starts(self):
        assert window_is_open(start_time=_NOW, end_time=_NOW + _HOUR, now=_NOW)

    def test_closed_at_the_moment_it_ends(self):
        assert not window_is_open(start_time=_NOW - _HOUR, end_time=_NOW, now=_NOW)


class TestAllowanceWindows:
    def test_the_open_windows_while_any_is_open(self):
        opened = _Window(1, _NOW - _HOUR, _NOW + _HOUR)
        ended = _Window(2, _NOW - 2 * _HOUR, _NOW - _HOUR)

        assert allowance_windows([ended, opened], now=_NOW) == [opened]

    def test_the_latest_to_end_once_all_have_closed(self):
        earlier = _Window(1, _NOW - 3 * _HOUR, _NOW - 2 * _HOUR)
        later = _Window(2, _NOW - 3 * _HOUR, _NOW - _HOUR)

        assert allowance_windows([later, earlier], now=_NOW) == [later]

    def test_none_before_the_first_one_opens(self):
        upcoming = _Window(1, _NOW + _HOUR, _NOW + 2 * _HOUR)

        assert allowance_windows([upcoming], now=_NOW) == []
        assert open_windows([upcoming], now=_NOW) == []


class TestSessionSeats:
    def test_no_window_leaves_the_session_limit_standing(self):
        seats = SessionSeatsDTO(
            participants_limit=_LIMIT, seating_percentage=None, enrolled_count=9
        )

        assert seats.effective_participants_limit == _LIMIT
        assert seats.seats_left == 1
        assert not seats.is_full

    def test_a_share_rounds_up(self):
        seats = SessionSeatsDTO(
            participants_limit=5, seating_percentage=50, enrolled_count=3
        )

        assert seats.effective_participants_limit == seats.enrolled_count
        assert seats.is_full
        assert seats.seats_left == 0

    def test_a_session_taking_no_enrollment_is_never_full(self):
        seats = SessionSeatsDTO(
            participants_limit=0, seating_percentage=None, enrolled_count=0
        )

        assert not seats.is_full


def test_email_domain_is_empty_without_an_at_sign():
    assert email_domain("someone@example.com") == "example.com"
    assert not email_domain("no-at-sign")
