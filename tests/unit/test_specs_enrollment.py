from datetime import UTC, datetime, timedelta

from ludamus.pacts.enrollment import (
    UNLIMITED_SLOTS,
    PromotionStateDTO,
    WaitingParticipantDTO,
)
from ludamus.pacts.legacy import PromotionMode
from ludamus.specs.enrollment import select_promotable_parties

_BASE = datetime(2026, 6, 4, 12, 0, tzinfo=UTC)


def _wp(
    pid,
    *,
    user_id=None,
    manager_id=None,
    order=0,
    has_conflict=False,
    is_active=True,
    slots=UNLIMITED_SLOTS,
):
    user_id = user_id if user_id is not None else pid
    return WaitingParticipantDTO(
        participation_id=pid,
        user_id=user_id,
        manager_id=manager_id,
        full_name=f"user-{pid}",
        email=f"u{pid}@example.com",
        is_active=is_active,
        creation_time=_BASE + timedelta(minutes=order),
        has_conflict=has_conflict,
        manager_slots_remaining=slots,
        recipient_user_id=manager_id if manager_id is not None else user_id,
        recipient_email=f"r{manager_id if manager_id is not None else user_id}@e.com",
    )


def _state(waiting, *, seats=1, presenter_id=None):
    return PromotionStateDTO(
        session_id=1,
        session_title="S",
        event_slug="ev",
        promotion_mode=PromotionMode.AUTO,
        offer_claim_window=timedelta(hours=24),
        presenter_id=presenter_id,
        available_seats=seats,
        waiting=waiting,
    )


class TestSelectPromotableParties:
    def test_no_seats_selects_nothing(self):
        state = _state([_wp(1)], seats=0)
        assert not select_promotable_parties(state)

    def test_fifo_single_seat_fills_first_party(self):
        state = _state([_wp(1, order=0), _wp(2, order=1)], seats=1)

        selected = select_promotable_parties(state)

        assert [p.participation_id for party in selected for p in party] == [1]

    def test_party_of_two_not_promoted_into_one_seat(self):
        party = [_wp(1, manager_id=99, order=0), _wp(2, manager_id=99, order=1)]
        state = _state(party, seats=1)

        assert not select_promotable_parties(state)

    def test_no_leapfrog_to_smaller_party_behind(self):
        waiting = [
            _wp(1, manager_id=99, order=0),
            _wp(2, manager_id=99, order=1),
            _wp(3, order=2),
        ]
        state = _state(waiting, seats=1)

        # The 2-person party is first and does not fit; the lone waiter behind
        # must not leapfrog it.
        assert not select_promotable_parties(state)

    def test_ineligible_member_dropped_rest_promoted(self):
        waiting = [
            _wp(1, manager_id=99, order=0, has_conflict=True),
            _wp(2, manager_id=99, order=1),
        ]
        state = _state(waiting, seats=2)

        selected = select_promotable_parties(state)

        assert [p.participation_id for party in selected for p in party] == [2]

    def test_all_ineligible_party_is_skipped_not_stopped(self):
        waiting = [_wp(1, order=0, has_conflict=True), _wp(2, order=1)]
        state = _state(waiting, seats=1)

        selected = select_promotable_parties(state)

        assert [p.participation_id for party in selected for p in party] == [2]

    def test_presenter_skipped(self):
        state = _state([_wp(1, user_id=7, order=0), _wp(2, order=1)], seats=1)
        state = state.model_copy(update={"presenter_id": 7})

        selected = select_promotable_parties(state)

        assert [p.participation_id for party in selected for p in party] == [2]

    def test_exhausted_membership_party_skipped(self):
        waiting = [_wp(1, order=0, slots=0), _wp(2, order=1)]
        state = _state(waiting, seats=2)

        selected = select_promotable_parties(state)

        assert [p.participation_id for party in selected for p in party] == [2]

    def test_partial_membership_holds_the_line(self):
        # Manager has 1 slot but a 2-person eligible party: does not fit, and
        # holds the line (strict FIFO) so the waiter behind is not promoted.
        waiting = [
            _wp(1, manager_id=99, order=0, slots=1),
            _wp(2, manager_id=99, order=1, slots=1),
            _wp(3, order=2),
        ]
        state = _state(waiting, seats=5)

        assert not select_promotable_parties(state)

    def test_fills_multiple_parties_until_seats_exhausted(self):
        waiting = [_wp(1, order=0), _wp(2, order=1), _wp(3, order=2)]
        state = _state(waiting, seats=2)

        selected = select_promotable_parties(state)

        assert [p.participation_id for party in selected for p in party] == [1, 2]

    def test_promotes_all_waiting_when_seats_remain(self):
        # Seats outnumber waiters: the walk runs off the end of the party list
        # (no break) and returns everyone promoted.
        waiting = [_wp(1, order=0), _wp(2, order=1)]
        state = _state(waiting, seats=5)

        selected = select_promotable_parties(state)

        assert [p.participation_id for party in selected for p in party] == [1, 2]
