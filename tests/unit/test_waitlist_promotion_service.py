import logging
import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from ludamus.mills.enrollment import WaitlistPromotionService
from ludamus.pacts.enrollment import (
    UNLIMITED_SLOTS,
    ClaimResult,
    HeldSeatData,
    OfferDTO,
    OfferRecipientDTO,
    PromotionNotification,
    PromotionResult,
    PromotionStateDTO,
    SeatHoldRequest,
    WaitingParticipantDTO,
)
from ludamus.pacts.legacy import PromotionMode
from tests.unit.factories import FakeTransaction

_NOW = datetime(2026, 6, 4, 12, 0, tzinfo=UTC)
_SESSION_ID = 42
_MANAGER_ID = 99
_MEMBER_ID = 7
_HELD_ID = 101
_URL_SAFE_TOKEN = re.compile(r"[A-Za-z0-9_-]{64}")


pytestmark = pytest.mark.usefixtures("_frozen")


@pytest.fixture
def _frozen(monkeypatch):
    monkeypatch.setattr("ludamus.mills.enrollment._now", lambda: _NOW)
    monkeypatch.setattr("ludamus.mills.enrollment._token", lambda: "tok-xyz")


class FakeRepo:
    def __init__(self, states=None, offer=None, lapsed=None):
        self._states = list(states or [])
        self._offer = offer
        self._lapsed = None if lapsed is None else list(lapsed)
        self.log = SimpleNamespace(
            confirmed=[],
            offered=[],
            created=[],
            claimed=[],
            dropped=[],
            locked=[],
            tokens_read=[],
            participations_read=[],
            members_read=[],
            claim_windows_read=[],
        )

    def list_lapsed_offers(self, now):
        # Mirrors the real repo: one representative per offered party whose
        # deadline has passed. An explicit `lapsed` seed stands in for several
        # such parties.
        if self._lapsed is not None:
            return list(self._lapsed)
        if self._offer is not None and self._offer.offer_expires_at < now:
            return [self._offer.participant_ids[0]]
        return []

    def create_offered(self, seat):
        self.log.created.append(seat)
        return _HELD_ID

    def read_offer_claim_window(self, session_id):
        self.log.claim_windows_read.append(session_id)
        return timedelta(hours=24)

    def lock_and_read_state(self, session_id):
        self.log.locked.append(session_id)
        return self._states.pop(0) if self._states else None

    def confirm(self, ids):
        self.log.confirmed.append(ids)

    def offer(self, ids, *, offered_at, offer_expires_at, claim_token):
        self.log.offered.append(
            {
                "ids": ids,
                "token": claim_token,
                "at": offered_at,
                "exp": offer_expires_at,
            }
        )

    def read_offer_by_token(self, token):
        self.log.tokens_read.append(token)
        return self._offer

    def read_offer_for_member(self, *, user_id, session_id):
        self.log.members_read.append((user_id, session_id))
        return self._offer if session_id == _SESSION_ID else None

    def read_offer_by_participation(self, participation_id):
        self.log.participations_read.append(participation_id)
        return self._offer

    def mark_claimed(self, ids, *, claimed_at):
        self.log.claimed.append((ids, claimed_at))

    def drop(self, ids):
        self.log.dropped.append(ids)


class FakeNotifier:
    def __init__(self):
        self.promoted = []
        self.offered = []
        self.expired = []
        self.held = []

    def notify_promoted(self, n):
        self.promoted.append(n)

    def notify_offered(self, n):
        self.offered.append(n)

    def notify_offer_expired(self, n):
        self.expired.append(n)

    def notify_seat_held(self, n):
        self.held.append(n)


class FakeScheduler:
    def __init__(self):
        self.scheduled: list[tuple[int, datetime]] = []

    def schedule_expiry(self, *, participation_id, run_at):
        self.scheduled.append((participation_id, run_at))


def _wp(pid, *, sponsor_id=None, order=0):
    return WaitingParticipantDTO(
        participation_id=pid,
        user_id=pid,
        party_id=None,
        sponsor_id=sponsor_id,
        full_name=f"user-{pid}",
        email=f"u{pid}@example.com",
        creation_time=_NOW + timedelta(minutes=order),
        has_conflict=False,
        owner_slots_remaining=UNLIMITED_SLOTS,
        recipient_user_id=sponsor_id if sponsor_id is not None else pid,
        recipient_email=f"r{sponsor_id if sponsor_id is not None else pid}@e.com",
    )


def _state(waiting, *, mode=PromotionMode.AUTO, seats=1):
    return PromotionStateDTO(
        session_id=_SESSION_ID,
        session_title="Dragons",
        event_slug="con",
        promotion_mode=mode,
        offer_claim_window=timedelta(hours=24),
        presenter_id=None,
        available_seats=seats,
        waiting=waiting,
    )


def _build(states=None, offer=None, lapsed=None):
    repo = FakeRepo(states=states, offer=offer, lapsed=lapsed)
    notifier = FakeNotifier()
    scheduler = FakeScheduler()
    service = WaitlistPromotionService(FakeTransaction(), repo, notifier, scheduler)
    return service, repo, notifier, scheduler


def _offer(*, expires):
    return OfferDTO(
        session_id=_SESSION_ID,
        session_title="Dragons",
        event_slug="con",
        participant_ids=[1, 2],
        recipients=[OfferRecipientDTO(user_id=_MANAGER_ID, email="r@e.com")],
        offer_expires_at=expires,
    )


class TestFillFreedSeats:
    def test_no_state_is_noop(self, caplog):
        service, repo, notifier, _ = _build(states=[None])

        with caplog.at_level(logging.INFO, logger="ludamus.mills.enrollment"):
            result = service.fill_freed_seats(session_id=_SESSION_ID)

        assert not result.promoted
        assert repo.log.locked == [_SESSION_ID]
        assert not repo.log.confirmed
        assert not notifier.promoted
        assert caplog.messages == [
            f"Session {_SESSION_ID} promotes nobody: it is gone or unscheduled"
        ]

    def test_no_waiters_is_noop(self, caplog):
        service, repo, _, _ = _build(states=[_state([])])

        with caplog.at_level(logging.INFO, logger="ludamus.mills.enrollment"):
            result = service.fill_freed_seats(session_id=_SESSION_ID)

        assert not result.promoted
        assert not repo.log.confirmed
        assert caplog.messages == [
            f"Session {_SESSION_ID} promotes nobody: 1 seats free, 0 waiting, mode auto"
        ]

    def test_auto_promotes_and_notifies(self):
        service, repo, notifier, scheduler = _build(states=[_state([_wp(1)])])

        result = service.fill_freed_seats(session_id=_SESSION_ID)

        assert result.promoted == [1]
        assert repo.log.confirmed == [[1]]
        assert len(notifier.promoted) == 1
        assert notifier.promoted[0].session_title == "Dragons"
        assert not scheduler.scheduled

    def test_offer_mode_holds_offers_schedules_and_notifies(self):
        service, repo, notifier, scheduler = _build(
            states=[_state([_wp(1)], mode=PromotionMode.OFFER_CLAIM)]
        )

        result = service.fill_freed_seats(session_id=_SESSION_ID)

        assert result.offered == [1]
        assert not result.promoted
        assert repo.log.offered == [
            {
                "ids": [1],
                "token": "tok-xyz",
                "at": _NOW,
                "exp": _NOW + timedelta(hours=24),
            }
        ]
        assert len(notifier.offered) == 1
        assert notifier.offered[0].claim_token == "tok-xyz"
        assert notifier.offered[0].offer_expires_at == _NOW + timedelta(hours=24)
        assert scheduler.scheduled == [(1, _NOW + timedelta(hours=24))]

    def test_offer_notifies_manager_for_managed_party(self):
        party = [
            _wp(1, sponsor_id=_MANAGER_ID, order=0),
            _wp(2, sponsor_id=_MANAGER_ID, order=1),
        ]
        service, repo, notifier, _ = _build(
            states=[_state(party, mode=PromotionMode.OFFER_CLAIM, seats=2)]
        )

        result = service.fill_freed_seats(session_id=_SESSION_ID)

        assert result.offered == [1, 2]
        assert repo.log.offered[0]["ids"] == [1, 2]
        assert notifier.offered[0].recipient_user_id == _MANAGER_ID


class TestClaimOffer:
    def _offer(self, *, expires=_NOW + timedelta(hours=1)):
        return OfferDTO(
            session_id=_SESSION_ID,
            session_title="Dragons",
            event_slug="con",
            participant_ids=[1, 2],
            recipients=[OfferRecipientDTO(user_id=_MANAGER_ID, email="r@e.com")],
            offer_expires_at=expires,
        )

    def test_valid_token_confirms_whole_party(self):
        service, repo, _, _ = _build(offer=self._offer())

        result = service.claim_offer(token="tok-xyz")

        assert result == ClaimResult(
            success=True, session_id=_SESSION_ID, event_slug="con"
        )
        assert repo.log.tokens_read == ["tok-xyz"]
        assert repo.log.claimed == [([1, 2], _NOW)]

    def test_a_token_claimed_on_its_deadline_still_counts(self):
        service, repo, _, _ = _build(offer=self._offer(expires=_NOW))

        result = service.claim_offer(token="tok-xyz")

        assert result.success is True
        assert repo.log.claimed == [([1, 2], _NOW)]

    def test_unknown_or_resolved_token_rejected(self):
        # A claimed/dropped party is no longer OFFERED, so the locked read
        # returns None — indistinguishable from an unknown token.
        service, repo, _, _ = _build(offer=None)

        result = service.claim_offer(token="nope")

        assert result.success is False
        assert result.reason == "not_found"
        assert not repo.log.claimed

    def test_past_deadline_rejected(self):
        service, repo, _, _ = _build(
            offer=self._offer(expires=_NOW - timedelta(minutes=1))
        )

        result = service.claim_offer(token="tok-xyz")

        assert result == ClaimResult(
            success=False, reason="expired", session_id=_SESSION_ID, event_slug="con"
        )
        assert not repo.log.claimed


class TestClaimMemberOffer:
    def test_members_own_offer_is_claimed_and_logged(self, caplog):
        service, repo, _, _ = _build(offer=_offer(expires=_NOW + timedelta(hours=1)))

        with caplog.at_level(logging.INFO, logger="ludamus.mills.enrollment"):
            result = service.claim_member_offer(
                user_id=_MEMBER_ID, session_id=_SESSION_ID
            )

        assert result == ClaimResult(
            success=True, session_id=_SESSION_ID, event_slug="con"
        )
        # A session id alone must never reach someone else's offer.
        assert repo.log.members_read == [(_MEMBER_ID, _SESSION_ID)]
        assert repo.log.claimed == [([1, 2], _NOW)]
        assert caplog.messages == [
            (
                f"Dashboard offer claim by member {_MEMBER_ID} "
                f"on session {_SESSION_ID}: claimed"
            )
        ]

    def test_offer_of_another_member_is_not_found_and_logged(self, caplog):
        # The lookup is scoped to this member's own seats, so someone else's
        # offered seat on the same session reads as nothing to claim.
        service, repo, _, _ = _build(offer=None)

        with caplog.at_level(logging.INFO, logger="ludamus.mills.enrollment"):
            result = service.claim_member_offer(
                user_id=_MEMBER_ID, session_id=_SESSION_ID
            )

        assert result == ClaimResult(success=False, reason="not_found")
        assert not repo.log.claimed
        assert caplog.messages == [
            (
                f"Dashboard offer claim by member {_MEMBER_ID} "
                f"on session {_SESSION_ID}: not_found"
            )
        ]

    def test_a_session_this_member_holds_no_offer_at_is_not_found(self, caplog):
        # The lookup is scoped to the session asked for, so the member's offer
        # on another session is nothing to claim here.
        other_session_id = _SESSION_ID + 1
        service, repo, _, _ = _build(offer=_offer(expires=_NOW + timedelta(hours=1)))

        with caplog.at_level(logging.INFO, logger="ludamus.mills.enrollment"):
            result = service.claim_member_offer(
                user_id=_MEMBER_ID, session_id=other_session_id
            )

        assert result == ClaimResult(success=False, reason="not_found")
        assert repo.log.members_read == [(_MEMBER_ID, other_session_id)]
        assert not repo.log.claimed
        assert caplog.messages == [
            (
                f"Dashboard offer claim by member {_MEMBER_ID} "
                f"on session {other_session_id}: not_found"
            )
        ]

    def test_past_deadline_is_rejected_and_logged(self, caplog):
        service, repo, _, _ = _build(offer=_offer(expires=_NOW - timedelta(minutes=1)))

        with caplog.at_level(logging.INFO, logger="ludamus.mills.enrollment"):
            result = service.claim_member_offer(
                user_id=_MEMBER_ID, session_id=_SESSION_ID
            )

        assert result == ClaimResult(
            success=False, reason="expired", session_id=_SESSION_ID, event_slug="con"
        )
        assert not repo.log.claimed
        assert caplog.messages == [
            (
                f"Dashboard offer claim by member {_MEMBER_ID} "
                f"on session {_SESSION_ID}: expired"
            )
        ]


class TestExpireOffer:
    def _offer(self, *, expires=_NOW - timedelta(minutes=1)):
        return OfferDTO(
            session_id=_SESSION_ID,
            session_title="Dragons",
            event_slug="con",
            participant_ids=[1, 2],
            recipients=[OfferRecipientDTO(user_id=_MANAGER_ID, email="r@e.com")],
            offer_expires_at=expires,
        )

    def test_lapsed_offer_dropped_notified_and_rolls_on(self):
        # First lock reads the lapsed offer for expiry; second lock (the
        # re-entry into fill_freed_seats) promotes the next waiter.
        repo = FakeRepo(states=[_state([_wp(3)])], offer=self._offer())
        notifier = FakeNotifier()
        scheduler = FakeScheduler()
        service = WaitlistPromotionService(FakeTransaction(), repo, notifier, scheduler)

        result = service.expire_offer(participation_id=1)

        assert repo.log.participations_read == [1]
        assert repo.log.dropped == [[1, 2]]
        assert notifier.expired == [
            PromotionNotification(
                recipient_user_id=_MANAGER_ID,
                recipient_email="r@e.com",
                session_id=_SESSION_ID,
                session_title="Dragons",
                event_slug="con",
            )
        ]
        # rolled on: the next waiter got the freed seat
        assert repo.log.locked == [_SESSION_ID]
        assert result.promoted == [3]
        assert repo.log.confirmed == [[3]]

    def test_already_resolved_offer_is_noop(self):
        # Claimed/dropped party is no longer OFFERED, so the locked read is None.
        service, repo, notifier, _ = _build(offer=None)

        result = service.expire_offer(participation_id=1)

        assert not repo.log.dropped
        assert not notifier.expired
        assert not result.promoted

    @pytest.mark.parametrize("expires", (_NOW + timedelta(hours=1), _NOW))
    def test_not_yet_due_is_noop(self, expires):
        service, repo, notifier, _ = _build(offer=self._offer(expires=expires))

        service.expire_offer(participation_id=1)

        assert not repo.log.dropped
        assert not notifier.expired
        assert not repo.log.locked


class TestExpireLapsedOffers:
    def test_expires_each_lapsed_party_once(self):
        offer = OfferDTO(
            session_id=_SESSION_ID,
            session_title="Dragons",
            event_slug="con",
            participant_ids=[1, 2],
            recipients=[OfferRecipientDTO(user_id=_MANAGER_ID, email="r@e.com")],
            offer_expires_at=_NOW - timedelta(minutes=1),
        )
        service, repo, notifier, _ = _build(states=[None], offer=offer)

        expired = service.expire_lapsed_offers(now=_NOW)

        assert expired == 1
        assert repo.log.participations_read == [1]
        assert repo.log.dropped == [[1, 2]]
        assert len(notifier.expired) == 1

    def test_expires_every_lapsed_party_and_counts_them(self):
        service, repo, _, _ = _build(
            lapsed=[1, 9], offer=_offer(expires=_NOW - timedelta(minutes=1))
        )

        count = service.expire_lapsed_offers(now=_NOW)

        assert count == len(repo.log.dropped)
        assert repo.log.dropped == [[1, 2], [1, 2]]

    def test_no_lapsed_offers_is_noop(self):
        service, repo, notifier, _ = _build()

        expired = service.expire_lapsed_offers(now=_NOW)

        assert expired == 0
        assert not repo.log.dropped
        assert not notifier.expired


class TestHoldSeat:
    def test_creates_offered_row_notifies_and_schedules(self):
        service, repo, notifier, scheduler = _build()

        service.hold_seat(
            hold=SeatHoldRequest(
                session_id=_SESSION_ID,
                session_title="Dragons",
                user_id=_MEMBER_ID,
                user_email="mira@example.com",
                party_id=5,
                actor_name="Lea Leader",
            )
        )

        assert repo.log.created == [
            HeldSeatData(
                session_id=_SESSION_ID,
                user_id=_MEMBER_ID,
                party_id=5,
                offered_at=_NOW,
                offer_expires_at=_NOW + timedelta(hours=24),
                claim_token="tok-xyz",
            )
        ]
        assert len(notifier.held) == 1
        held = notifier.held[0]
        assert held.recipient_user_id == _MEMBER_ID
        assert held.recipient_email == "mira@example.com"
        assert held.actor_name == "Lea Leader"
        assert held.claim_token == "tok-xyz"
        assert held.offer_expires_at == _NOW + timedelta(hours=24)
        assert repo.log.claim_windows_read == [_SESSION_ID]
        assert scheduler.scheduled == [(_HELD_ID, _NOW + timedelta(hours=24))]


class TestDeclineOffer:
    def _offer(self):
        return OfferDTO(
            session_id=_SESSION_ID,
            session_title="Dragons",
            event_slug="con",
            participant_ids=[1, 2],
            recipients=[OfferRecipientDTO(user_id=_MANAGER_ID, email="r@e.com")],
            offer_expires_at=_NOW + timedelta(hours=1),
        )

    def test_drops_whole_party_and_rolls_on(self):
        service, repo, notifier, _ = _build(
            states=[_state([_wp(3)])], offer=self._offer()
        )

        result = service.decline_offer(token="tok-xyz")

        assert result == ClaimResult(
            success=True, session_id=_SESSION_ID, event_slug="con"
        )
        assert repo.log.tokens_read == ["tok-xyz"]
        assert repo.log.dropped == [[1, 2]]
        # The freed seats rolled on to the next waiter.
        assert repo.log.locked == [_SESSION_ID]
        assert repo.log.confirmed == [[3]]
        assert [n.recipient_user_id for n in notifier.promoted] == [3]

    def test_unknown_or_resolved_token_rejected(self):
        service, repo, _, _ = _build(offer=None)

        result = service.decline_offer(token="nope")

        assert result.success is False
        assert result.reason == "not_found"
        assert not repo.log.dropped


class TestPeekOffer:
    def test_returns_the_offer_behind_the_token(self):
        offer = _offer(expires=_NOW + timedelta(hours=1))
        service, repo, _, _ = _build(offer=offer)

        assert service.peek_offer(token="tok-xyz") == offer
        assert repo.log.tokens_read == ["tok-xyz"]

    def test_unknown_token_is_none(self):
        service, _, _, _ = _build()

        assert service.peek_offer(token="tok-xyz") is None


class TestFillFreedSeatsOutcomes:
    def test_no_free_seat_promotes_nobody(self):
        service, repo, notifier, _ = _build(states=[_state([_wp(1)], seats=0)])

        result = service.fill_freed_seats(session_id=_SESSION_ID)

        assert result == PromotionResult()
        assert not repo.log.confirmed
        assert not notifier.promoted

    def test_offer_mode_arms_one_expiry_per_party(self):
        service, repo, notifier, scheduler = _build(
            states=[_state([_wp(1), _wp(2, order=1)], mode=PromotionMode.OFFER_CLAIM)]
        )

        result = service.fill_freed_seats(session_id=_SESSION_ID)

        assert result.offered == [1]
        assert repo.log.offered == [
            {
                "ids": [1],
                "token": "tok-xyz",
                "at": _NOW,
                "exp": _NOW + timedelta(hours=24),
            }
        ]
        assert notifier.offered[0].offer_expires_at == _NOW + timedelta(hours=24)
        assert scheduler.scheduled == [(1, _NOW + timedelta(hours=24))]

    def test_a_fresh_claim_token_is_long_and_url_safe(self, monkeypatch):
        monkeypatch.undo()
        service, repo, _, _ = _build(
            states=[_state([_wp(1)], mode=PromotionMode.OFFER_CLAIM)]
        )

        service.fill_freed_seats(session_id=_SESSION_ID)

        assert _URL_SAFE_TOKEN.fullmatch(repo.log.offered[0]["token"])
