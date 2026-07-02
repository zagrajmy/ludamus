from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest

from ludamus.mills.enrollment import WaitlistPromotionService
from ludamus.pacts.enrollment import (
    UNLIMITED_SLOTS,
    HeldSeatData,
    OfferDTO,
    OfferRecipientDTO,
    PromotionStateDTO,
    SeatHoldRequest,
    WaitingParticipantDTO,
)
from ludamus.pacts.legacy import PromotionMode

_NOW = datetime(2026, 6, 4, 12, 0, tzinfo=UTC)
_SESSION_ID = 42
_MANAGER_ID = 99
_MEMBER_ID = 7


pytestmark = pytest.mark.usefixtures("_frozen")


@pytest.fixture
def _frozen(monkeypatch):
    monkeypatch.setattr("ludamus.mills.enrollment._now", lambda: _NOW)
    monkeypatch.setattr("ludamus.mills.enrollment._token", lambda: "tok-xyz")


@contextmanager
def _atomic():
    yield


class FakeTransaction:
    @staticmethod
    def atomic():
        return _atomic()


class FakeRepo:
    def __init__(self, states=None, offer=None):
        self._states = list(states or [])
        self._offer = offer
        self.confirmed: list[list[int]] = []
        self.offered: list[dict] = []
        self.created: list[dict] = []
        self.claimed: list[list[int]] = []
        self.dropped: list[list[int]] = []

    def create_offered(self, seat):
        self.created.append(seat)
        return 101

    @staticmethod
    def read_offer_claim_window(_session_id):
        return timedelta(hours=24)

    def lock_and_read_state(self, _session_id):
        return self._states.pop(0) if self._states else None

    def confirm(self, ids):
        self.confirmed.append(ids)

    def offer(self, ids, *, offer_expires_at, claim_token, **_kwargs):
        self.offered.append({"ids": ids, "token": claim_token, "exp": offer_expires_at})

    def read_offer_by_token(self, _token):
        return self._offer

    def read_offer_by_participation(self, _participation_id):
        return self._offer

    def mark_claimed(self, ids, **_kwargs):
        self.claimed.append(ids)

    def drop(self, ids):
        self.dropped.append(ids)


class FakeNotifier:
    def __init__(self):
        self.promoted = []
        self.offered = []
        self.expired = []
        self.held = []

    def notify_seat_held(self, n):
        self.held.append(n)

    def notify_promoted(self, n):
        self.promoted.append(n)

    def notify_offered(self, n):
        self.offered.append(n)

    def notify_offer_expired(self, n):
        self.expired.append(n)


class FakeScheduler:
    def __init__(self):
        self.scheduled = []

    def schedule_expiry(self, *, participation_id, run_at):
        self.scheduled.append((participation_id, run_at))


def _wp(pid, *, sponsor_id=None, party_id=None, order=0):
    return WaitingParticipantDTO(
        participation_id=pid,
        user_id=pid,
        party_id=party_id,
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


def _build(states=None, offer=None):
    repo = FakeRepo(states=states, offer=offer)
    notifier = FakeNotifier()
    scheduler = FakeScheduler()
    service = WaitlistPromotionService(FakeTransaction(), repo, notifier, scheduler)
    return service, repo, notifier, scheduler


class TestFillFreedSeats:
    def test_no_state_is_noop(self):
        service, repo, notifier, _ = _build(states=[None])

        result = service.fill_freed_seats(session_id=_SESSION_ID)

        assert not result.promoted
        assert not repo.confirmed
        assert not notifier.promoted

    def test_no_waiters_is_noop(self):
        service, repo, _, _ = _build(states=[_state([])])

        result = service.fill_freed_seats(session_id=_SESSION_ID)

        assert not result.promoted
        assert not repo.confirmed

    def test_auto_promotes_and_notifies(self):
        service, repo, notifier, scheduler = _build(states=[_state([_wp(1)])])

        result = service.fill_freed_seats(session_id=_SESSION_ID)

        assert result.promoted == [1]
        assert repo.confirmed == [[1]]
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
        assert repo.offered == [
            {"ids": [1], "token": "tok-xyz", "exp": _NOW + timedelta(hours=24)}
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
        assert repo.offered[0]["ids"] == [1, 2]
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

        assert result.success is True
        assert result.session_id == _SESSION_ID
        assert repo.claimed == [[1, 2]]

    def test_unknown_or_resolved_token_rejected(self):
        # A claimed/dropped party is no longer OFFERED, so the locked read
        # returns None — indistinguishable from an unknown token.
        service, repo, _, _ = _build(offer=None)

        result = service.claim_offer(token="nope")

        assert result.success is False
        assert result.reason == "not_found"
        assert not repo.claimed

    def test_past_deadline_rejected(self):
        service, repo, _, _ = _build(
            offer=self._offer(expires=_NOW - timedelta(minutes=1))
        )

        result = service.claim_offer(token="tok-xyz")

        assert result.success is False
        assert result.reason == "expired"
        assert not repo.claimed


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

        assert repo.dropped == [[1, 2]]
        assert len(notifier.expired) == 1
        assert notifier.expired[0].recipient_user_id == _MANAGER_ID
        # rolled on: the next waiter got the freed seat
        assert result.promoted == [3]
        assert repo.confirmed == [[3]]

    def test_already_resolved_offer_is_noop(self):
        # Claimed/dropped party is no longer OFFERED, so the locked read is None.
        service, repo, notifier, _ = _build(offer=None)

        result = service.expire_offer(participation_id=1)

        assert not repo.dropped
        assert not notifier.expired
        assert not result.promoted

    def test_not_yet_due_is_noop(self):
        service, repo, notifier, _ = _build(
            offer=self._offer(expires=_NOW + timedelta(hours=1))
        )

        service.expire_offer(participation_id=1)

        assert not repo.dropped
        assert not notifier.expired


class TestPartyRecipients:
    def test_party_of_real_users_notifies_each_member(self):
        state = _state(
            [_wp(1, party_id=5, order=0), _wp(2, party_id=5, order=1)], seats=2
        )
        repo = FakeRepo([state])
        notifier = FakeNotifier()
        service = WaitlistPromotionService(
            FakeTransaction(), repo, notifier, FakeScheduler()
        )

        result = service.fill_freed_seats(session_id=1)

        assert result.promoted == [1, 2]
        assert sorted(n.recipient_user_id for n in notifier.promoted) == [1, 2]


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

        assert repo.created == [
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
        assert scheduler.scheduled == [(101, _NOW + timedelta(hours=24))]


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
        service, repo, _, _ = _build(states=[_state([_wp(3)])], offer=self._offer())

        result = service.decline_offer(token="tok-xyz")

        assert result.success is True
        assert result.event_slug == "con"
        assert repo.dropped == [[1, 2]]
        # The freed seats rolled on to the next waiter.
        assert repo.confirmed == [[3]]

    def test_unknown_or_resolved_token_rejected(self):
        service, repo, _, _ = _build(offer=None)

        result = service.decline_offer(token="nope")

        assert result.success is False
        assert result.reason == "not_found"
        assert not repo.dropped
